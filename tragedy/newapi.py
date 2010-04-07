import time
import functools
from collections import OrderedDict
from cassandra.ttypes import (Column, ColumnOrSuperColumn, ColumnParent,
    ColumnPath, ConsistencyLevel, NotFoundException, SlicePredicate,
    SliceRange, SuperColumn)

def gm_timestamp():
    """int : UNIX epoch time in GMT"""
    return int(time.time() * 1e6)

class RowDefaults(object):
    default_transformer = None
    timestamp = staticmethod(gm_timestamp)
    read_consistency_level=ConsistencyLevel.ONE
    write_consistency_level=ConsistencyLevel.ONE

    def _wcl(self, alternative):
        return alternative if alternative else self.read_consistency_level

    def _rcl(self, alternative):
        return alternative if alternative else self.read_consistency_level

class BasicRow(RowDefaults):
    """A row has (keyspace, column_family, row_key_name) fixed already."""
    def __init__(self):
        self.sanityCheck_init()
        # Storage
        self.ordered_columnkeys = OrderedDict() # basically abused as OrderedSet
        self.column_value    = {}  #
        self.column_spec     = {}  # these have no order themselves, but the keys are the same as above
    
    def sanityCheck_init(self):
        meta = getattr(self, 'Meta', False)
        assert meta, "Need to define Meta!"
        assert getattr(meta, 'column_family', False), 'Need to define Meta.column_family'
        assert getattr(meta, 'keyspace', False), 'Need to define Meta.keyspace'
        assert getattr(meta, 'client', False), 'Need to define Meta.client'

    def sanityCheck_save(self):
        assert self.Meta.row_key_name in self.ordered_columnkeys.keys(), 'Need row_key specified somehow!'
    
    def calc_kvpairs(self, filter_for_saving=False):
        for columnkey in self.ordered_columnkeys.keys():
            transformer = self.column_spec.get(columnkey, self.default_transformer)
            if transformer:
                newvalue = transformer(columnkey, self.column_value.get(columnkey))
                self.column_value[columnkey] = newvalue
                            
            if self.column_value.get(columnkey) is None:
                continue
            if filter_for_saving and (columnkey == self.Meta.row_key_name):
                continue
                        
            yield columnkey, self.column_value[columnkey]
       
    def insert(self, write_consistency_level=None):
        self.sanityCheck_save()
        save_columns = []
        for columnkey, columnvalue in self.calc_kvpairs(filter_for_saving=True):
            column = Column(name=columnkey, value=columnvalue, timestamp=self.timestamp())
            save_columns.append( ColumnOrSuperColumn(column=column) )
                
        self.Meta.client.batch_insert(keyspace         = self.Meta.keyspace,
                                 key              = self.column_value[self.Meta.row_key_name],
                                 cfmap            = {self.Meta.column_family: save_columns},
                                 consistency_level= self._wcl(write_consistency_level),
                                )
    
    @property
    def partial_get_columns_from_one_row(self):
        column_parent = ColumnParent(column_family=self.Meta.column_family, super_column=None)
        func = functools.partial(self.Meta.client.get_range_slice, 
                                 keyspace          = self.Meta.keyspace,
                                 column_parent     = column_parent,
                                 #predicate
                                 start_key         = self.column_value[self.Meta.row_key_name],
                                 finish_key        = self.column_value[self.Meta.row_key_name],
                                 row_count         = 1,
                                 #consistency_level
                                )
        return func
    
    def get_slice_predicate(self, column_names=None, start='', finish='', reverse=False, count=10000):
        if column_names:
            return SlicePredicate(column_names=columns)
            
        slice_range = SliceRange(start=start, finish=finish, reversed=reverse, count=count)
        return SlicePredicate(slice_range=slice_range)
    
    def get_last_n_columns(self, n=10000, consistency_level=None):
        predicate = self.get_slice_predicate(count=n)
        key_slices = self.partial_get_columns_from_one_row(predicate=predicate,
                                                       consistency_level=self._rcl(consistency_level)
                                                      )
        if not key_slices:
            return None # empty
        assert len(key_slices) == 1, 'we requested one row, but got more'
        result = key_slices[0]
        assert result.key == self.column_value[self.Meta.row_key_name]
        return result
    
    def load(self, spec_for_new_column=None):
        try:
            rowkey, freshcolumns = (self.objects.column_family.get_range(start=self.key, finish=self.key,
                                   column_start='', column_finish='', column_reversed=False, column_count=column_count, row_count=1)).next()
        except StopIteration:
            raise Exception("Received zero answers to query.")
        assert self.key == rowkey, "Received different key %s than what I asked for (%s)" % (rowkey, self.key)
    
    def __str__(self):
        return repr(OrderedDict( (x,y) for (x,y) in self.calc_kvpairs()))
from .datastructures import (OrderedDict,)
from .util import (CASPATHSEP,
                   CrossModelCache,
                  )

cmcache = CrossModelCache()

class InventoryType(type):
    """This keeps inventory of the models created, and prepares the
       limited amount of metaclass magic that we do. keep this small!"""
    def __new__(cls, name, bases, attrs):
        parents = [b for b in bases if isinstance(b, InventoryType)]
        new_cls = super(InventoryType, cls).__new__(cls, name, bases, attrs)
                
        if '__abstract__' in new_cls.__dict__:
            return new_cls
        
        new_cls._init_class()
        new_cls._keyspace.register_model(getattr(new_cls, '_column_family', name), new_cls)

        return new_cls

class Cluster(object):
    def __init__(self, name):
        self.keyspaces = OrderedDict()
        self.name = name
        self._client = None
        
        cmcache.append('clusters', self)
    
    def setclient(self, client):
        self._client = client
    
    def getclient(self):
        if not self._client:
            clients = cmcache.retrieve('clients')
            if clients and clients[0]:
                self._client = clients[0]
        assert self._client, 'No Client set for Cluster or dependents.'
        return self._client
    
    def registerKeyspace(self, name, keyspc):
        self.keyspaces[name] = keyspc
        
    def __str__(self):
        return self.name

class Keyspace(object):
    def __init__(self, name, cluster):
        self.models = OrderedDict()
        self.name = name
        self.cluster = cluster
        cluster.registerKeyspace(self.name, self)
        
        cmcache.append('keyspaces', self)

    def getclient(self):
        return self.cluster.getclient()

    def path(self):
        return u'%s%s%s' % (self.cluster.name, CASPATHSEP, self.name)

    def register_model(self, name, model):
        self.models[name] = model

    def __str__(self):
        return self.name

    def register_keyspace_with_cassandra(self):
        self.getclient().system_add_keyspace()

    def verify_datamodel(self, fix=False):
        for model in self.models.values():
            self.verify_datamodel_for_model(model, fix=fix)
    
    @staticmethod
    def verify_datamodel_for_model(cls, fix=False):
        allkeyspaces = cls.getclient().describe_keyspaces()
        if not cls._keyspace.name in allkeyspaces:
            print "Cassandra doesn't know about keyspace %s (only %s)" % (cls._keyspace, allkeyspaces)
            cls._keyspace.register_keyspace_with_cassandra()
            raise NotImplementedError
        mykeyspace = cls.getclient().describe_keyspace(cls._keyspace.name)
        assert cls._column_family in mykeyspace.keys(), "Cassandra doesn't know about ColumnFamily '%s'. Update your config and restart?" % (cls._column_family,)
        mycf = mykeyspace[cls._column_family]
        assert cls._column_type == mycf['Type'], "Cassandra expects Column Type '%s' for ColumnFamily %s. Tragedy thinks it is '%s'." % (mycf['Type'], cls._column_family, cls._column_type)
        remotecw = mycf['CompareWith'].rsplit('.',1)[1]
        assert cls._default_field.compare_with == remotecw, "Cassandra thinks ColumnFamily '%s' is sorted by '%s'. Tragedy thinks it is '%s'." % (cls._column_family, remotecw, cls._default_field.compare_with)

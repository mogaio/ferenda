from rdflib import URIRef
from rdflib.namespace import RDF, RDFS, DC, SKOS
from rdflib.namespace import DCTERMS as DCT

from ferenda import fulltextindex # to get the IndexedType classes

class Facet(object):
    @staticmethod
    def defaultselector(row, binding):
        return row[binding]
      
    @staticmethod
    def firstletter(row, binding='dcterms_title'):
        return titlesortkey(row, binding)[0]

    @staticmethod
    def year(row, binding='dcterms_issued'):
        # assume a date(time) on the form 2014-06-05, the year == the first 4 chars
        return row[binding][:4]

    @staticmethod
    def titlesortkey(row, binding='dcterms_title'):
        title = row[binding].lower()
        if title.startswith("the "):
            title = title[4:]
            # filter away starting non-word characters (but not digits)
            title = re.sub("^\W+", "", title)
            # remove whitespace
            return "".join(title.split())

    @staticmethod
    def resourcelabel(row, binding='dcterms_publisher', resourcegraph=None):
        uri = URIRef(row[binding])
        for pred in (rdfs.label, skos.prefLabel, skos.altLabel, dct.title, dct.alternative):
            if resourcegraph.value(uri, pred):
                return str(resourcegraph.value(uri, pred))
        else:
            return row[binding]

    @staticmethod
    def sortresource(row, binding='dcterms_publisher', resourcegraph=None):
        row[binding] = resourcelabel(row, binding, resourcegraph)
        return titlesortkey(row, binding)

    # define a number of default values, used if the user does not
    # explicitly specify indexingtype/selector/key
    defaults = {RDF.type: {
                    'indextype': fulltextindex.URI(),
                    'toplevel_only': False,
                    'use_for_toc'  : False}, # -> selector etc are irrelevant
                DCT.title: {
                    'indextype': fulltextindex.Text(boost=4),
                    'toplevel_only': False,
                    'use_for_toc': True, 
                    'selector': firstletter,
                    'key': titlesortkey,
                    'selector_descending': False,
                    'key_descending': False
                },
                DCT.identifier: {
                    'indextype': fulltextindex.Label(boost=16),
                    'toplevel_only': False,
                    'use_for_toc': True, 
                    'selector': firstletter,
                    'key': titlesortkey,
                    'selector_descending': False,
                    'key_descending': False
                },
                DCT.abstract: {
                    'indextype': fulltextindex.Text(boost=2),
                    'toplevel_only': True,
                    'use_for_toc': False
                },
                DC.creator:{
                    'indextype': fulltextindex.Label(),
                    'toplevel_only': True,
                    'use_for_toc': True,
                    'selector': firstletter,
                    'key': titlesortkey,
                    'selector_descending': False,
                    'key_descending': False
                },
                DC.publisher:{
                    'indextype': fulltextindex.Resource(),
                    'toplevel_only': True,
                    'use_for_toc': True,
                    'selector': firstletter,
                    'key': sortresource,
                    'selector_descending': False,
                    'key_descending': False
                },
                DC.issued:{
                    'indextype': fulltextindex.Datetime(),
                    'toplevel_only': True,
                    'use_for_toc': True,
                    'selector': year,
                    'key': defaultselector,
                    'selector_descending': True,
                    'key_descending': True
                }
            }
    # formatting directives for label/pagetitle:
    # %(criteria)s = The human-readable criteria for sorting/dividing/faceting, eg "date of publication", "document title" or "publisher"
    # %(selected)s = The selected value, eg "2014", "A", "O'Reilly and Associates Publishing, inc."
    # %(selected_uri)s = For resource-type values, the underlying URI, eg "http://example.org/ext/publisher/oreilly"
    def __init__(self,
                 rdftype=DCT.title, # any rdflib.URIRef
                 label="Sorted by %(criteria)s", # toclabel
                 pagetitle="Documents where %(criteria)s = %(selected)s",
                 indexingtype=None,   # if not given, determined by rdftype
                 selector=None,       # - "" -
                 key=None,            # - "" -
                 toplevel_only=None,  # - "" -
                 use_for_toc=None     # - "" -
             ):
        
        def _finddefault(provided, rdftype, argumenttype, default):
            if provided is None:
                if rdftype in self.defaults and argumenttype in self.defaults[rdftype]:
                    return mapping[rdftype][argumenttype]
                else:
                    log = logging.getLogger(__name__)
                    log.warning("Cannot map rdftype %s with argumenttype %s, defaulting to %r" %
                                (rdftype, argumenttype, default))
                    return default                
            else:
                return provided

        self.rdftype = rdftype
        self.label = label
        self.pagetitle = pagetitle
        self.indexingtype        = _finddefault(indexingtype, rdftype, 'indexingtype', fulltextindex.Text())
        self.selector            = _finddefault(selector, rdftype, 'selector', defaultselector)
        self.key                 = _finddefault(key, rdftype, 'key', defaultselector)
        self.toplevel_only       = _finddefault(toplevel_only, rdftype, 'toplevel_only', False)
        self.use_for_toc         = _finddefault(use_for_toc, rdftype, 'use_for_toc', False)
        self.selector_descending = _finddefault(selector_descending, rdftype, 'selector_descending', False)
        self.key_descending      = _finddefault(key_descending, rdftype, 'key_descending', False)

    # backwards compatibility shim:
    def as_criteria(self):
        return TocCriteria(util.uri_leaf(str(self.rdftype)),
                           self.label,
                           self.pagetitle,
                           self.selector, # might need to wrap these functions to handle differing arg lists
                           self.key,      # - "" -
                           self.selector_descending,
                           self.key_descending,
                           self.rdftype)

    # There should be a way to construct a SPARQL SELECT query from a list of Facets that retrieve all needed data
    # The needed data should be a simple 2D table, where each Facet is represented by one OR MORE fields 
    #    (ie a dct:publisher should result in the binding "dcterms_publisher" and "dcterms_publisher_label")
 
    # There must be a way to get a machine-readable label/identifier for each facet. This is used:
    # - for variable binding in the sparql query
    # - for field names in the fulltext index
    # preferably "dct_title", "rdf_type", etc

    # There should be a way to determine which fields that are to be indexed in the fulltext index. This should be based 
    #    on the rdftype (determines how we find the content/value of the facet) and the indexingtype (how we store it).

    # The fulltext index stores a number of fields not directly associated with a Facet:
    # - uri / iri (has corresponding value in the SPARQL SELECT results)
    # - repo (is not represented in the SPARQL SELECT results)
    # - basefile (is not represented either)

    # General modeling:
    # if the rdftype is dct:publisher, dct:creator, dct:subject, the indexingtype SHOULD be fulltextindex.Resource 
    #    (ie the triple should be a URIRef, not Literal, and we store both resource IRI and label)
    # if we can only get Literals, use dc:publisher, dc:creator, dc:subject.
           
   

# should/must work for

# Facets that occur at all documentlevels
# - Document or sectional type (rdftype=rdf.type, indexingtype=fulltext.URI(), use_for_toc=False, toplevel_only=False)
# - Title (rdftype=dct.title, indexingtype=fulltextindex.Text(boost=4), toplevel_only=False)
# - Identifier (rdftype=dct.identifier, indexingtype=fulltextindex.Label(boost=16), toplevel_only=False, use_for_toc=False) # or True, iff a custom selector method is used (like in RFC.py)

# Facets that only occur at document top level
# - Abstract (rdftype=dct.abstract, indexingtype=fulltextindex.Text(boost=2))
# - Author (rdftype=dc.creator, indexingtype=fulltextindex.Label()) # ie author is modelled as a Literal
# - Publisher (rdftype=dct.publisher, indexingtype=fulltextindex.Resource()) # publisher is modelled as URIRef, a Literal label is picked from the document or extra/[docrepo].ttl
# - Literal publisher (rdftype=dc.publisher, indexingtype=fulltextindex.Label()) # publisher modelled as Literal
# - Publication date (rdftype=dct.issued, indexingtype=fulltextindex=Datetime())

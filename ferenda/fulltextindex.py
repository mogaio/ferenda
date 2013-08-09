from pprint import pprint
import re

from ferenda import util

class FulltextIndex(object):

    @staticmethod
    def connect(indextype, location):
        """Open a fulltext index (creating it if it
        doesn't already exists).

        :param location: Type of fulltext index (right now only "WHOOSH" is
                         supported)
        :type  location: str
        :param location: The file path of the fulltext index.
        :type  location: str
    """
        # create correct subclass and return it
        return WhooshIndex(location)

    def __init__(self, location):
        self.location = location
        if self.exists():
            self.index = self.open()
        else:
            self.index = self.create(self.get_default_schema())
        

    def __del__(self):
        self.close()

    def get_default_schema(self):
        return {'uri':Identifier(),
                'repo':Label(),
                'basefile':Label(),
                'title':Text(boost=4),
                'identifier':Label(boost=16),
                'text':Text()}        

    def exists(self):
        raise NotImplementedError

    def create(self, schema):
        raise NotImplementedError

    def open(self):
        raise NotImplementedError

    def schema(self):
        """Returns the schema in use. A schema is a dict where the keys are field names 
           and the values are any subclass of :py:class:`ferenda.fulltextindex.IndexedType`"""
        return self.get_default_schema()

    def update(self, uri, repo, basefile, title, identifier, text, **kwargs):
        """Insert (or update) a resource in the fulltext index. A resource may
        be an entire document, but it can also be any part of a
        document that is referenceable (i.e. a document node that has
        ``@typeof`` and ``@about`` attributes). A document with 100
        sections can be stored as 100 independent resources, as long
        as each section has a unique key in the form of a URI.

        :param uri: URI for the resource
        :type  uri: str
        :param repo: The alias for the document repository that the resource is part of
        :type  repo: str
        :param basefile: The basefile which contains resource
        :type  basefile: str
        :param title: User-displayable title of resource (if applicable). Should not 
                      contain the same information as ``identifier``. 
        :type  title: str
        :param identifier: User-displayable short identifier for resource (if applicable)
        :type  identifier: str
        :type  text: The full textual content of the resource, as a plain string.
        :type  text: str

        .. note::

           Calling this method may not directly update the fulltext
           index -- you need to call :meth:`commit` or :meth:`close`
           for that.

        """
        raise NotImplementedError

    def commit(self):
        """Commit all pending updates to the fulltext index."""
        raise NotImplementedError

    def close(self):
        """Commits all pending updates and closes the index."""
        raise NotImplementedError
            

    def doccount(self):
        """Returns the number of currently indexed (non-deleted) documents."""
        raise NotImplementedError        

    def query(self,q, **kwargs):
        """Perform a free text query against the full text index, optionally restricted with
           parameters for individual fields.

        :param q: Free text query, using the selected full text index's prefered query syntax
        :type  q: str
        :param **kwargs: any parameter will be used to match a similarly-named field
        :type **kwargs: dict
        :returns: matching documents, each document as a dict of fields
        :rtype: list

        .. note::

           The *kwargs* parameters do not yet do anything -- only
           simple full text queries are possible.

        """
        raise NotImplementedError

class IndexedType(object):
    """Base class for a fulltext searchengine-independent representation
       of indeaxed data.  By using IndexType-derived classes to
       represent the schema, it becomes possible to switch out search
       engines without affecting the rest of the code.

    """
    def __eq__(self, other):
        return (isinstance(other, self.__class__)
                and self.__dict__ == other.__dict__)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(tuple(v for k, v in sorted(self.__dict__.items())))
    
    def __init__(self,**kwargs):
        self.__dict__ = dict(kwargs)

    def __repr__(self):
        # eg '<Label boost=16>' or '<Identifier>'
        dictrepr = "".join((" %s=%s"%(k,v) for k,v in sorted(self.__dict__.items())))
        return ("<%s%s>" % (self.__class__.__name__, dictrepr))
    
    
class Identifier(IndexedType): pass
class Datetime(IndexedType): pass
class Text(IndexedType): pass
class Label(IndexedType): pass
class Keywords(IndexedType): pass
class Boolean(IndexedType): pass
class URI(IndexedType): pass

class SearchModifier(object): pass
class Less(SearchModifier): pass
class More(SearchModifier): pass
class Between(SearchModifier): pass


import whoosh.index
import whoosh.fields
import whoosh.analysis
import whoosh.query
import whoosh.qparser
import whoosh.writing
import whoosh.highlight

from ferenda.elements import html

class ElementsFormatter(whoosh.highlight.Formatter):
    """Returns a tree of ferenda.elements representing the formatted hit."""

    def __init__(self, wrapelement=html.P, hitelement=html.Strong, classname="match", between=" ... "):
        self.wrapelement = wrapelement
        self.hitelement = hitelement
        self.classname = classname
        self.between = between

    def format(self, fragments, replace=False):
        res = self.wrapelement()
        first = True
        for fragment in fragments:
            if not first:
                res.append(self.between)
            res.extend(self.format_fragment(fragment, replace=replace))
            first = False
        return res

    re_collapse = re.compile("\s+").sub
    def format_fragment(self, fragment, replace):
        output = []
        index = fragment.startchar
        text = fragment.text

        for t in fragment.matches:
            if t.startchar > index:
                output.append(self.re_collapse(" ",text[index:t.startchar]))
            hittext = whoosh.highlight.get_text(text,t,False)
            output.append(self.hitelement([hittext], **{'class': self.classname}))
            index = t.endchar
        if index < len(text):
            output.append(self.re_collapse(" ",text[index:fragment.endchar]))
        return output


class WhooshIndex(FulltextIndex):

    def __init__(self,location):
        super(WhooshIndex, self).__init__(location)
        self._schema = self.get_default_schema()
        self._writer = None
        self._batchwriter = False


    def exists(self):
        return whoosh.index.exists_in(self.location)
         

    def open(self):
        return whoosh.index.open_dir(self.location)


    def create(self, schema):
        # maps our field classes to concrete whoosh field instances
        mapped_field = {Identifier():   whoosh.fields.ID(unique=True, stored=True),
                        Label():        whoosh.fields.ID(stored=True),
                        Label(boost=16):whoosh.fields.ID(field_boost=16,stored=True),
                        Text(boost=4):  whoosh.fields.TEXT(field_boost=4,stored=True,
                                                           analyzer=whoosh.analysis.StemmingAnalyzer()),
                        Text():         whoosh.fields.TEXT(stored=True,
                                                           analyzer=whoosh.analysis.StemmingAnalyzer())}
                        
        whoosh_fields = {}
        for key,fieldtype in self.get_default_schema().items():
            whoosh_fields[key] = mapped_field[fieldtype]
        schema = whoosh.fields.Schema(**whoosh_fields)
        util.mkdir(self.location)
        return whoosh.index.create_in(self.location,schema)


    def schema(self):
        return self._schema

    
    def update(self, uri, repo, basefile, title, identifier, text, **kwargs):
        if not self._writer:
            if self._batchwriter:
                self._writer = whoosh.writing.BufferedWriter(self.index, limit=1000)
            else:
                self._writer = self.index.writer()

        # A whoosh document is not the same as a ferenda document. A
        # ferenda document may be indexed as several (tens, hundreds
        # or more) whoosh documents
        self._writer.update_document(uri=uri,
                                     repo=repo,
                                     basefile=basefile,
                                     title=title,
                                     identifier=identifier,
                                     text=text,
                                      **kwargs)
        

    def commit(self):
        if self._writer:
            self._writer.commit()
            if not isinstance(self._writer, whoosh.writing.BufferedWriter):
                # A bufferedWriter can be used again after commit(), a regular writer cannot
                self._writer = None


    def close(self):
        self.commit()
        if self._writer:
            self._writer.close()
            self._writer = None
            

    def doccount(self):
        return self.index.doc_count()


    def query(self,q, pagenum=1, pagelen=10, **kwargs):
        searchfields = ['identifier','title','text']
        mparser = whoosh.qparser.MultifieldParser(searchfields,
                                                  self.index.schema)
        query = mparser.parse(q)
        with self.index.searcher() as searcher:
            page = searcher.search_page(query, pagenum, pagelen)
            res = self._convert_result(page)
            pager = {'pagenum': pagenum,
                     'pagecount':page.pagecount,
                     'firstresult':page.offset+1,
                     'lastresult': page.offset+page.pagelen,
                     'totalresults': page.total}
        return res, pager


    def _convert_result(self,res):
        # converts a whoosh.searching.ResultsPage object to a plain
        # list of dicts
        l = []
        hl = whoosh.highlight.Highlighter(formatter=ElementsFormatter())
        for hit in res:
            fields = hit.fields()
            fields['text'] = hl.highlight_hit(hit,"text",fields['text'])
            l.append(hit.fields())	
        return l

# Base class for a HTTP-based API (eg. ElasticSearch)
class RemoteIndex(FulltextIndex):

    import requests


    def exists(self): pass

    def create(self, schema):
        payload = self._create_schema_payload()
        requests.put(self.location, payload)

    def open(self): pass
    def schema(self): pass
    def update(self, uri, repo, basefile, title, identifier, text, **kwargs): pass
    def commit(self): pass
    def close(self): pass
    def doccount(self): pass
    def query(self,q, **kwargs): pass

class ElasticSearchIndex(RemoteIndex):
    def _create_schema_payload():
        pass


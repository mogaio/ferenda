# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import *

from ferenda import DocumentRepository, util, errors
from ferenda.testutil import RepoTester
from ferenda.decorators import updateentry
# SUT
from ferenda import CompositeRepository


class SubrepoA(DocumentRepository):
    storage_policy = "file"
    alias= "a"
    def download(self, basefile=None):
        util.writefile(self.store.downloaded_path("1"), "basefile 1, repo a")
        util.writefile(self.store.downloaded_path("3"), "basefile 3, repo a")

    @updateentry("parse")
    def parse(self, basefile):
        if basefile in ("1", "3"):
            util.writefile(self.store.parsed_path(basefile),
                           "basefile %s, parsed by a" % basefile)
            util.writefile(self.store.distilled_path(basefile),
                           "basefile %s, metadata from a" % basefile)
            return True
        else:
            return False # we don't even have this basefile

    def custom(self):
        return False
        
class SubrepoB(DocumentRepository):
    storage_policy = "dir"
    alias= "b"
    def download(self, basefile=None):
        util.writefile(self.store.downloaded_path("1"), "basefile 1, repo b")
        util.writefile(self.store.downloaded_path("2"), "basefile 2, repo b")

    @updateentry("parse")
    def parse(self, basefile):
        if basefile == "1":
            util.writefile(self.store.parsed_path("1"),
                           "basefile 1, parsed by b")
            util.writefile(self.store.parsed_path("1", attachment="attach.txt"),
                           "attachment for basefile 1, parsed by b")
            util.writefile(self.store.distilled_path("1"),
                           "basefile 1, metadata from b")
            return True
        else:
            raise errors.ParseError("No can do!")

    @classmethod
    def get_default_options(cls):
        opts = super(SubrepoB, cls).get_default_options()
        opts['customproperty'] = "Hello world!"
        return opts

    def custom(self):
        return self.config.customproperty


class SubrepoASubclass(SubrepoA): pass

class SubrepoBSubclass(SubrepoB):
    def qualified_class_name(self):
        return "Q:" + super(SubrepoBSubclass,
                            self).qualified_class_name()


class CompositeExample(CompositeRepository):
    subrepos = SubrepoBSubclass, SubrepoASubclass
    storage_policy = "dir"

    def custom(self):
        for c in self.subrepos:
            inst = self.get_instance(c)
            ret = inst.custom()
            if ret:
                return ret
        raise RuntimeError("No subrepo could perform custom method")

    def qualified_class_name(self):
        for c in self.subrepos:
            inst = self.get_instance(c)
            ret = inst.qualified_class_name()
            if ret:
                return ret
        raise RuntimeError("No subrepo could perform qualified_class_name")


class TestComposite(RepoTester):
    repoclass = CompositeExample
 
    def test_download(self):
        self.repo.download()
        self.assertEqual("basefile 1, repo a",
                         util.readfile(self.datadir+"/a/downloaded/1.html"))
        self.assertEqual("basefile 1, repo b",
                         util.readfile(self.datadir+"/b/downloaded/1/index.html"))
        self.assertEqual("basefile 2, repo b",
                         util.readfile(self.datadir+"/b/downloaded/2/index.html"))
        self.assertEqual("basefile 3, repo a",
                         util.readfile(self.datadir+"/a/downloaded/3.html"))

    def test_list_basefiles_for(self):
        self.repo.download()
        self.assertEqual(set(["3", "2", "1"]),
                         set(self.repo.store.list_basefiles_for("parse")))

    def test_parse(self):
        self.repo.download()
        self.assertTrue(self.repo.parse("1")) # both A and B can
                                              # handle this but B
                                              # should win
        self.assertEqual("basefile 1, parsed by b",
                         util.readfile(self.repo.store.parsed_path("1")))
        self.assertEqual("basefile 1, metadata from b",
                         util.readfile(self.repo.store.distilled_path("1")))
        self.assertEqual(["attach.txt"],
                         list(self.repo.store.list_attachments("1", "parsed")))
        with self.assertRaises(errors.ParseError):
            self.assertFalse(self.repo.parse("2")) # none can handle this
        self.assertTrue(self.repo.parse("3")) # only A can handle this
        self.assertEqual("basefile 3, parsed by a",
                         util.readfile(self.repo.store.parsed_path("3")))
        self.assertEqual("basefile 3, metadata from a",
                         util.readfile(self.repo.store.distilled_path("3")))
        self.assertEqual([], # this repo supports attachment, but
                             # underlying repo A did not
                         list(self.repo.store.list_attachments("3", "parsed")))
                        
        # in this case, all files should be up-to-date, so no copying
        # should occur (triggering the "Attachments are (likely)
        # up-to-date branch")
        self.assertTrue(self.repo.parse("1")) 

        # and finally, list_basefiles_for("generate") should delegate
        # to DocumentStore.list_basefiles_for
        self.assertEqual(set(["1", "3"]),
                         set(self.repo.store.list_basefiles_for("generate")))

    def test_config(self):
        # test it with self.repo being initialized with some kwargs parameters
        self.repo.download()
        got = self.repo.custom()
        self.assertEqual("Hello world!", got)

        # now test with external config object -- this is where it'll fail
#        self.repo = CompositeExample()
#        self.repo.config = LayeredConfig(Defaults({'datadir': self.datadir}))
#        got = self.repo.custom()
#        self.assertEqual("Hello world!", got)


class Mixin(object):
    def custom(self):
        return "Hello world from mixin"

class CompositeExtrabase(CompositeExample):
    extrabases = (Mixin,)


class TestExtrabase(RepoTester):

    repoclass = CompositeExtrabase

    def test_config(self):
        got = self.repo.custom()
        self.assertEqual("Hello world from mixin", got)

    def test_super(self):
        got = self.repo.qualified_class_name()
        self.assertEqual("Q:testCompositeRepo.SubrepoBSubclass", got)

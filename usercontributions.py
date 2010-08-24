#!/usr/bin/env python

##########################################################################
#                                                                        #
#  This program is free software; you can redistribute it and/or modify  #
#  it under the terms of the GNU General Public License as published by  #
#  the Free Software Foundation; version 2 of the License.               #
#                                                                        #
#  This program is distributed in the hope that it will be useful,       #
#  but WITHOUT ANY WARRANTY; without even the implied warranty of        #
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         #
#  GNU General Public License for more details.                          #
#                                                                        #
##########################################################################

from datetime import datetime
import os
import sys
import re
import numpy as np
import guppy

## PROJECT LIBS
import sonet.mediawiki as mwlib
from sonet.lib import find_open_for_this_file
from sonet.timr import Timr

class UserContrib(object):
    #__slots__ = ['namespace_count',]
    normal_count = 0
    namespace_count = None
    first_time = None
    last_time = None

    def __init__(self, attr_len):
        self.namespace_count = np.zeros((attr_len,), dtype=np.int)
    def inc_normal(self):
        self.normal_count += 1
    def inc_namespace(self, idx):
        self.namespace_count[idx] += 1
    def time(self, time_):
        if self.first_time is None or self.first_time > time_:
            self.first_time = time_
        if self.last_time is None or self.last_time < time_:
            self.last_time = time_

class ContribDict(dict):
    def __init__(self, namespaces):
        super(ContribDict, self).__init__()
        self._namespaces = namespaces
        self._d_namespaces = dict([(name.decode('utf-8'), idx) for idx, (key,
            name) in enumerate(namespaces)])
        print self._d_namespaces

    def append(self, user, page_title, time_):
        try:
            contrib = self[user]
        except:
            contrib = UserContrib(len(self._namespaces))
            self[user] = contrib

        ## Namespace
        a_title = page_title.split(':')
        if len(a_title) == 1:
            contrib.inc_normal()
        else:
            try:
                contrib.inc_namespace(self._d_namespaces[a_title[0]])
            except KeyError:
                contrib.inc_normal()

        ## Time
        contrib.time(time_)

class UserContributionsPageProcessor(mwlib.PageProcessor):
    """
    UserContributionsPageProcessor extracts a graph from a meta-history or a
    stub-meta-history dump.

    A state-machine-like approach is used to parse the file.

    Only tag-end events are used. (eg. in <a><b></b></a> the first event is for
    the <b> tag, then the one for <a>).

    The entry point is process_title (one per page). Then, in every page there
    are many revisions, and each one has timestamp and contributor tags.

    <page>
        <title>Title</title>
        <revision>
            <timestamp>...<timestamp>
            <contributor>...</contributor>
        </revision>
        (... more revisions ...)
    </page>
    """
    __slots__ = tuple()
    # to limit the extraction to changes before a datetime
    time_end = None
    # to limit the extraction to changes after a datetime
    time_start = None
    _re_welcome = None
    __welcome_pattern = None
    contribution = None
    __namespaces = None
    counter_deleted = 0

    @property
    def namespaces(self):
        return self.__namespaces

    @namespaces.setter
    def namespaces(self, namespaces):
        self.__namespaces = namespaces
        self.contribution = ContribDict(namespaces)

    @property
    def welcome_pattern(self):
        return self.__welcome_pattern

    @welcome_pattern.setter
    def welcome_pattern(self, value):
        self.__welcome_pattern = value
        self._re_welcome = re.compile(value, flags=re.IGNORECASE)

    ## PAGE RELATED VARIABLES
    _skip = False
    _title = None

    ## REVISION RELATED VARIABLES
    _time = None ## time of this revision
    _welcome = False
    _skip_revision = False
    _sender = None

    def process_title(self, elem):
        self._title = elem.text

    def process_timestamp(self, elem):
        timestamp = elem.text
        year = int(timestamp[:4])
        month = int(timestamp[5:7])
        day = int(timestamp[8:10])
        hour = int(timestamp[11:13])
        minutes = int(timestamp[14:16])
        seconds = int(timestamp[17:19])
        self._time = datetime(year, month, day, hour, minutes, seconds)

    def process_contributor(self, contributor):
        if self._skip_revision: return

        if contributor is None:
            print 'contributor is None'
            self._skip_revision = True

        sender_tag = contributor.find(self.tag['username'])
        if sender_tag is None:
            try:
                self._sender = contributor.find(self.tag['ip']).text
                if self._sender is None: self._skip_revision = True
            except AttributeError:
                ## user deleted
                self._skip_revision = True
                self.counter_deleted += 1
        else:
            try:
                self._sender = mwlib.capfirst(
                    sender_tag.text.replace('_', ' ')
                )
            except AttributeError:
                ## if username is defined but empty, look for id tag
                self._sender = contributor.find(self.tag['id']).text

    def process_comment(self, elem):
        if self._skip_revision: return
        assert self._welcome == False, 'processor._welcome is True!'
        #print elem.text.encode('utf-8')
        if not elem.text: return
        if self._re_welcome.search(elem.text):
            self._welcome = True

    def process_revision(self, _):
        skip, self._skip_revision = self._skip_revision or self._skip, False
        welcome, self._welcome = self._welcome, False
        if skip: return

        assert self._sender is not None, "Sender still not defined"
        assert self._title is not None, "Page title not defined"
        assert self._time is not None, "time not defined"

        self.contribution.append(self._sender, self._title, self._time)

        self._sender = None

    def process_page(self, _):
        if self._skip:
            self._skip = False
            return

        self._title = None

        self.count += 1
        if not self.count % 500:
            print >>sys.stderr, self.count

    def end(self):
        print 'END'


def opt_parse():
    from optparse import OptionParser
    from sonet.lib import SonetOption

    p = OptionParser(usage="usage: %prog [options] dumpfile",
                     option_class=SonetOption)
    p.add_option('-s', '--start', action="store",
        dest='start', type="yyyymmdd", metavar="YYYYMMDD", default=None,
        help="Look for revisions starting from this date")
    p.add_option('-e', '--end', action="store",
        dest='end', type="yyyymmdd", metavar="YYYYMMDD", default=None,
        help="Look for revisions until this date")
    opts, args = p.parse_args()

    ## CHECK IF OPTIONS ARE OK
    if len(args) != 1:
        p.error("Wrong number of arguments")
    if not os.path.exists(args[0]):
        p.error("Dump file does not exist (%s)" % (xml,))
    return (opts, args)


def main():
    opts, args = opt_parse()
    xml = args[0]

    ## SET UP FOR PROCESSING
    lang, date_, type_ = mwlib.explode_dump_filename(xml)

    deflate, _lineno = find_open_for_this_file(xml)

    if _lineno:
        src = deflate(xml, 51)
    else:
        src = deflate(xml)

    tag = mwlib.getTags(src,
        tags='page,title,revision,timestamp,contributor,username,ip,comment,id')

    namespaces = mwlib.getNamespaces(src)

    src.close()
    print >>sys.stderr, "BEGIN PARSING"
    src = deflate(xml)

    processor = UserContributionsPageProcessor(tag=tag)
    processor.namespaces = namespaces
    ##TODO: only works on it.wikipedia.org! :-)
    processor.welcome_pattern = r'Benvenut'
    processor.start(src) ## PROCESSING



if __name__ == "__main__":
    #import cProfile as profile
    #profile.run('main()', 'mainprof')
    main()
    h = guppy.hpy()
    print h.heap()
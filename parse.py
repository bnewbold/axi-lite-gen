#!/usr/bin/env python
"""

TODO:
- values should only parse as section if XYZ???
- whitespace control
  http://jinja.pocoo.org/docs/templates/#whitespace-control
- disable HTML safety for non-html documents?
"""

from __future__ import print_function

import sys
import csv
import time
import os

import jinja2

AXI_ADDR_BITS = 16
WORD_BITS = 32

def parse_slug(s):
    pre = s.split('[')[0]
    post = None
    assert(pre == filter(lambda x: x.isalnum() or x is '_', pre))
    assert(len(pre) >= 1 and pre[0] != '_')
    if '[' in s:
        assert(s.count('[') == 1)
        assert(s.count(']') == 1 and s[-1] == ']')
        post = int(s.split('[')[1][:-1])
        assert(post >= 0)
    return (pre, post)

def str2val(s, bits):
    """
    Strip '_' characters (eg, 0x1111_2222).
    Allow 0x and 0b prefixes.
    """
    v = None
    s = s.lower().replace('_', '')
    if s.count("'") is 1:
        raise NotImplementedError("Can't handle verilog-style constants yet")
    if s.startswith('0b'):
        v = int(s[2:], 2)
    if s.startswith('0x'):
        v = int(s[2:], 16)
    else: # fallback
        v = int(s)
    assert(v >= 0 and v < 2**bits)
    return v

class Value():
    index = None
    bits = None
    section = None
    section_index = None
    slug = None
    slug_index = None
    default = None
    description = None
    mode = None
    addr = None

    def offset(self, offset):
        self.addr = offset + (4 * self.index)

    def addr_pp(self):
        return "0x%08X" % self.addr

    def __init__(self, word_index=None, bits=None, section=None, slug=None,
                 default=None, description=None, mode=None):
        # TODO: input validation/transforms
        self.index = int(word_index)
        assert(self.index >= 0)
        assert(self.index <= (2**AXI_ADDR_BITS - 1))

        if bits in [None, '']:
            raise ValueError("Bits not defined")
        self.bits = str2val(bits, 9)
        assert(self.bits >= 1)
        assert(self.bits <= 128)

        if section is None:
            (self.section, self.section_index) = ('top_level', None)
        else:
            (self.section, self.section_index) = parse_slug(section)

        if slug is None:
            (self.slug, self.slug_index) = (None, None)
        else:
            (self.slug, self.slug_index) = parse_slug(slug)

        if default not in [None, '']:
            self.default = str2val(default, self.bits)
        else:
            self.default = 0
        self.description = description
        self.mode = mode

    def __str__(self):
        return "<Value: %s>" % str(self.__dict__)

class Register(Value):
    read = False
    write = False

class Parameter(Value):
    pass

def check_overlaps(l):
    rangelist = []
    for val in l:
        # TODO: also handle larger ranges
        this = (val.index, val.index + ((val.bits-1)/WORD_BITS))
        inserted = False
        for i in range(len(rangelist)):
            that = rangelist[i]
            if ((that[0] <= this[0] <= that[1])
                    or (that[0] <= this[1] <= that[1])):
                raise ValueError("Overlapping memory ranges: %s and %s" %
                    (this, that))
            if this[0] < that[0]:
                rangelist.insert(i, this)
                inserted = True
                break
        if not inserted:
            rangelist.append(this)

def check_names(l):
    names = []
    n = None
    for val in l:
        if val.section:
            n = "%s.%s" % (val.section, val.slug)
        else:
            n = val.slug
        if n in names:
            raise ValueError("Dupliate name: %s" % n)
        names.append(n)

def error(s="unspecified"):
    sys.stderr.write(str(s) + '\n')
    sys.exit(-1)

class Repeated():
    section = None

    def __init__(self, word_index, slug):
        self.index = int(word_index)
        assert(self.index >= 0)
        assert(self.index <= (2**AXI_ADDR_BITS - 1))

        if self.section is '':
            self.section = ''
            self.section_index = None
        else:
            (self.section, self.section_index) = parse_slug(section)
   

req = ('word_index', 'bits', 'mode', 'section', 'slug', 'default',
       'description')

print("------- START READ")
f = open('example.csv', 'r')
reader = csv.DictReader(f)

registers = []
parameters = []
mode = None

for line in reader:
    if reader.line_num is 0:
        # validate fields just once
        for field in req:
            if not field in reader.fields:
                error("Missing column: %s" % field)

    # skip lines w/o 
    if line['word_index'] in [None, '']:
        print("Skipping line %d (no index)" % reader.line_num)
        continue

    mode = line['mode']
    try:
        if mode.lower() == 'p':
            p = Parameter(**line)
            parameters.append(p)
        elif mode.lower() == 'r':
            r = Register(**line)
            r.read = True
            registers.append(r)
        else:
            #error("Unknown mode: %s" % mode)
            print("Skipping line %d (unknown mode %s)" % (reader.line_num,
                                                          mode))
            pass
    except (AttributeError, TypeError, ValueError), e:
        error("Syntax error parsing line %d: %s" % (reader.line_num, e))
    sys.stdout.write(".")
print('')
f.close()

print("Registers:\t%d" % len(registers))
print("Parameters:\t%d" % len(parameters))

offset = 0x0
for r in registers:
    r.offset(offset)
for p in parameters:
    p.offset(offset)

check_overlaps(registers + parameters)
check_names(registers + parameters)
sections = {}
for val in (registers + parameters):
    if not val.section in sections.keys():
        sections[val.section] = []
    sections[val.section].append(val)

for key, sec in sections.iteritems():
    sections[key] = sorted(sec, key=lambda x: x.index)

print("------- END READ")

# TODO: process into sections; sort; apply offsets

context = dict(registers=registers,
               parameters=parameters,
               name="example",
               now=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
               attribution="Generated by AXI-Lite Generator",
               whoami=os.getenv('USER'),
               sections=sections)

# TODO:
# jinja2.ChoiceLoader
# jinja2.PackageLoader
env = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'))
#print("------- START PYTHON")
"""
params: single helper to dump them all
registers:
    helper get/set by string (eg, get("meta.magic"))
    module cmd to dump them all
    module+slug cmd to get/set
    <section>.<slug> getter/setter functions
"""
#print("------- END PYTHON")

#print("------- START HDL")
"""
wrapper stub also.
params: passed all around
registers: just one place
"""
#print("------- END HDL")

#print("------- START C_HEADER")
"""
just structs for parameters/registers
"""
#print("------- END C_HEADER")

print("------- START HTML")
t = env.get_template('minimal.html.tmpl')
out_f = open('output/example.html', 'w')
out_f.write(t.render(**context))
out_f.close()
print("------- END HTML")

print("------- START RST")
t = env.get_template('minimal.rst.tmpl')
out_f = open('output/example.rst', 'w')
out_f.write(t.render(**context))
out_f.close()
print("------- END RST")

print("------- DONE!")


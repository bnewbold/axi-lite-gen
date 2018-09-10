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

import argparse
import os

AXI_DATA_WIDTH = 32
AXI_ADDR_WIDTH = 16
AXI_ADDR_MSB = AXI_ADDR_WIDTH-1
AXI_ADDR_LSB = 2

required_fields = ('word_index', 'bits', 'mode', 'section', 'slug',
        'default', 'description')

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
    signed = False

    def set_offset(self, offset):
        self.addr = offset + (4 * self.index)

    def addr_pp(self):
        return "0x%08X" % self.addr

    def __init__(self, word_index=None, bits=None, section=None, slug=None,
                 default=None, description=None, mode=None):
        # TODO: input validation/transforms
        self.index = int(word_index)
        assert(self.index >= 0)
        assert(self.index <= (2**AXI_ADDR_WIDTH - 1))

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

    def hdlwidth(self):
        if self.bits == 1:
            return "[0]"
        else:
            return "[%d:0] " % (self.bits - 1)

    def pphdlwidth(self):
        if self.bits == 1:
            return ""
        else:
            return "[%d:0] " % (self.bits - 1)

    def ppdefault(self):
        return "%d'h%X" % (self.bits, self.default)

    def word_list(self):
        l = []
        b = self.bits
        bottom = 0
        a = self.index
        span = None
        while b > 0:
            if b < 32:
                if (self.bits == 1):
                    span = ""
                else:
                    span = "[%d:%d]" % (bottom+b-1, bottom)
                l.append((a, "{%d'd0, %s%s}" % (32-b, self.slug, span), span))
            else:
                if (self.bits == 1):
                    span = ""
                else:
                    span = "[%d:%d]" % (bottom+31, bottom)
                l.append((a, "%s%s" % (self.slug, span), span))
            a += 1
            b -= 32
            bottom += 32
        return l

    def ctype(self):
        if self.bits <= 32:
            return self.signed and "int32_t" or "uint32_t"
        elif self.bits <= 64:
            return self.signed and "int64_t" or "uint64_t"
        else:
            raise ValueError("Can't represent %d bits in C... ?" % self.bits)


class Register(Value):
    read = False
    write = False


class Parameter(Value):
    def ppslug(self):
        return self.slug.upper()


def check_overlaps(l):
    rangelist = []
    for val in l:
        # TODO: also handle larger ranges
        this = (val.index, val.index + ((val.bits-1)/AXI_DATA_WIDTH))
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
    """
    Checks that all section+slug combinations are unique (no duplicates)
    'l' should be the set of all values, in any order.
    """
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


def check_gaps(l):
    """
    Checks for gaps between memory map locations within a section.
    Assumes 'l' is a list of values in a section, already sorted by index.
    """
    n = None
    for v in l:
        if n is not None:
            if v.index != n:
                raise Exception("Gap between values! Oh no! At: %s.%s (n=%d)"
                                % (v.section, v.slug, n))
        n = v.index + 1 + (v.bits-1)/32


def error(s="unspecified"):
    sys.stderr.write(str(s) + '\n')
    sys.exit(-1)


def parse(inFile):
    print("------- START READ")
    f = open(inFile, 'r')
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

        mode = line['mode'].lower()
        try:
            if mode == 'p':
                p = Parameter(**line)
                parameters.append(p)
            elif mode in ['r', 'w', 'rw', 'wr']:
                r = Register(**line)
                r.read = 'r' in mode
                r.write = 'w' in mode
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
        r.set_offset(offset)
    for p in parameters:
        p.set_offset(offset)

    check_overlaps(registers + parameters)
    check_names(registers + parameters)
    sections = {}
    for val in (registers + parameters):
        if not val.section in sections.keys():
            sections[val.section] = []
        sections[val.section].append(val)

    for key, sec in sections.iteritems():
        sections[key] = sorted(sec, key=lambda x: x.index)
        check_gaps(sections[key])

    print("------- END READ")
    return registers, parameters, sections


def output(registers, parameters, sections, name):
    settings = {
        'stub_axi_nets': True,
        'stub_nets': True,
    }
    context = dict(registers=registers,
                parameters=parameters,
                name=name,
                now=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                attribution="Generated by AXI-Lite Generator",
                whoami=os.getenv('USER'),
                sections=sections,
                AXI_DATA_WIDTH=int(AXI_DATA_WIDTH),
                AXI_ADDR_WIDTH=int(AXI_ADDR_WIDTH),
                AXI_STRB_WIDTH=int(AXI_DATA_WIDTH/8-1),
                AXI_ADDR_MSB=AXI_ADDR_MSB,
                AXI_ADDR_LSB=AXI_ADDR_LSB,
                settings=settings)

    def guess_autoescape(template_name):
        """Only auto-escape HTML documents"""
        if template_name is None:
            return False
        if 'html' in template_name.lower():
            return True
        else:
            return False

    # TODO:
    # jinja2.ChoiceLoader
    # jinja2.PackageLoader

    baseDir = os.environ["AXI_LITE_GEN"]
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(baseDir+'/templates'),
                            lstrip_blocks=True,
                            trim_blocks=True,
                            autoescape=guess_autoescape,
                            extensions=['jinja2.ext.autoescape'])
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

    print("------- START HDL")
    """
    wrapper stub also.
    params: passed all around
    registers: just one place
    """
    t = env.get_template('partial_axi_lite_slave.v.tmpl')
    out_f = open('output/axi_lite_slave_%s.v' % context['name'], 'w')
    out_f.write(t.render(**context))
    out_f.close()

    t = env.get_template('stub.v.tmpl')
    out_f = open('output/%s_stub.v' % context['name'], 'w')
    out_f.write(t.render(**context))
    out_f.close()
    print("------- END HDL")

    #print("------- START C_HEADER")
    """
    just structs for parameters/registers
    """
    t = env.get_template('headers.h.tmpl')
    out_f = open('output/%s_headers.h' % context['name'], 'w')
    out_f.write(t.render(**context))
    out_f.close()
    #print("------- END C_HEADER")

    print("------- START HTML")
    t = env.get_template('minimal.html.tmpl')
    out_f = open('output/%s.html' % context['name'], 'w')
    out_f.write(t.render(**context))
    out_f.close()
    print("------- END HTML")

    print("------- START RST")
    t = env.get_template('minimal.rst.tmpl')
    out_f = open('output/%s.rst' % context['name'], 'w')
    out_f.write(t.render(**context))
    out_f.close()
    print("------- END RST")

    print("------- DONE!")

def main():
    parser =  argparse.ArgumentParser(description = "Creates an axi-lite interface")
    parser.add_argument("inFile",help="cvs file to parse")
    parser.add_argument("-n","--name",default="example",help="Used as basename for output files and in the output files for parts of module names, ect.")
    args = parser.parse_args()
    r, p, s = parse(args.inFile)
    output(r,p,s,args.name)

if __name__=="__main__":
    main()

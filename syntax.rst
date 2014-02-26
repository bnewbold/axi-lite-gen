
Repetition
-----------------------
Repeated sections use array ([n]) syntax for the section name. The [0] section
should be complete, all the other repetitions should only have the word_index
set.

UNIMPLEMENTED: repeated sections could be packed/unpacked automatically (see
pack_array for macros)

HDL: Variables and Storage
-------------------------------------
Read-only nets are implemented

Mode Flags
----------------------

**r: Read**

**w: Write**

**p: Parameter**
    A special read-only mode for compile-time constants. The slug name is
    capitalized for HDL but lower case in other contexts.

**b: Doorbell**
    UNIMPLEMENTED.
    A new net with "_trig" suffix is created which is triggered on every write
    transaction.

**m: Memory Block**
    UNIMPLEMENTED.
    Uses an address mask to read/write, eg, a BRAM or regfile instead of
    exposing many individual registers.

**f: FIFO**
    UNIMPLEMENTED.
    Sets up a read or write FIFO.

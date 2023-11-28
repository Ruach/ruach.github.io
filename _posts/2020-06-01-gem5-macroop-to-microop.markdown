---
layout: post
titile: "Macroop Parsing with Python-Lex-Yacc"
categories: [GEM5, Macroop, Microops, PLY]
---

## Macroop and Microop in Computer Architecture                                

1. **Macroop (Macro-operation):**
   - A macroop is a high-level instruction or operation that is part of the
     instruction set architecture (ISA) of a processor. It represents a single
     operation that a program wants to perform, such as adding two numbers or
     loading a value from memory.
   - Macroops are what programmers typically interact with when writing code, as 
     they correspond to the instructions in the assembly language or machine
     code.

2. **Microop (Micro-operation or μop):**
   - A microop is a low-level operation that a processor's control unit
     decomposes a macroop into during the execution phase. It is a fundamental 
     operation that the processor can execute directly.
   - Processors often use micro-operations internally to break down complex
     macroops into simpler, more manageable tasks. These tasks are then executed 
     in the processor's pipeline.

In summary, the execution of a program involves the translation of macroops
(high-level instructions in the ISA) into a sequence of microops (low-level
operations) that the processor can execute efficiently. This translation allows 
for more parallel and optimized execution within the processor's pipeline.

### Mov macroop implementation in GEM5
As an illustration of defining each macroop based on microops, let's see the
how Mov instruction in the X86 architecture can be implemented with microops. 

```python
# gem5/src/arch/x86/isa/insts/general_purpose/data_transfer/move.py

microcode = '''

#
# Regular moves
#

def macroop MOV_R_MI {
    limm t1, imm, dataSize=asz
    ld reg, seg, [1, t0, t1]
};

def macroop MOV_MI_R {
    limm t1, imm, dataSize=asz
    st reg, seg, [1, t0, t1]
};
```

As depicted in the provided code, every macrooperation (macroop) is composed of
several microoperations (microops). Consequently, the processor transforms the 
macroop into a series of microops and proceeds to execute these microops rather
than the original macroop. You may wonder about the process by which these
macroop definitions are parsed and interpreted as the microoperations, allowing 
the processor to execute them within the pipeline. I will give you the details 
in this posting!

## GEM5 Domain Specific Language (DSL) and Python-Lex-Yacc (PLY)
You may notice a resemblance between the code that defines the macroop semantics 
and Python syntax; nevertheless, it's crucial to clarify that the code is not 
written in Python. GEM5 utilizes Domain-Specific Languages (DSL) to implement 
ISA including macroops and microops. As it is not a Python, it can be directly
interpreted as it is, and PLY generates lexer and parser to interpret the ISA
defined with GEM5. Therefore,  it is highly recommended to read 
[this tutorial about PLY][1] before continuing reading this posting.

Based on the predefined rules, GEM5 converts the macroops and microops
implemented in the predefined DSL into corresponding python classes. As similar
to how GEM5 generates CPP implementations for Params required for instantiating
the hardware module in CPP, the goal of the parsing ISA is generating CPP 
implementations that can be utilized during simulation, for example to decode 
instruction and execute them in the processor pipeline. 

### Parsing Instruction Set Architecture (ISA)
Since GEM5 utilize SCons, it generates Actions and Builders to process input 
and generate output files as a result. Since the expected result of the parsing
ISA of the target architecture is CPP implementations of the target ISA, the 
SConscript initiates the parsing before compiling the CPP code base. Let's see
how the SConscript initiates the parsing.

```python
#gem5/src/arch/SConscript
parser_py = File('isa_parser.py')
micro_asm_py = File('micro_asm.py')

import ply

def run_parser(target, source, env):
    # Add the current directory to the system path so we can import files.
    sys.path[0:0] = [ parser_py.dir.abspath ]
    import isa_parser

    parser = isa_parser.ISAParser(target[0].dir.abspath)
    parser.parse_isa_desc(source[0].abspath)

desc_action = MakeAction(run_parser, Transform("ISA DESC", 1))

IsaDescBuilder = Builder(action=desc_action)

......

def ISADesc(desc, decoder_splits=1, exec_splits=1):
    generated_dir = File(desc).dir.up().Dir('generated')
    def gen_file(name):
        return generated_dir.File(name)

    gen = []
    def add_gen(name):
        gen.append(gen_file(name))

    # Tell scons about the various files the ISA parser will generate.
    add_gen('decoder-g.cc.inc')
    add_gen('decoder-ns.cc.inc')
    add_gen('decode-method.cc.inc')

    add_gen('decoder.hh')
    add_gen('decoder-g.hh.inc')
    add_gen('decoder-ns.hh.inc')

    add_gen('exec-g.cc.inc')
    add_gen('exec-ns.cc.inc')

    add_gen('max_inst_regs.hh')


    # These generated files are also top level sources.
    def source_gen(name):
        add_gen(name)
        Source(gen_file(name))

    source_gen('decoder.cc')

    if decoder_splits == 1:
        source_gen('inst-constrs.cc')
    else:
        for i in range(1, decoder_splits + 1):
            source_gen('inst-constrs-%d.cc' % i)

    if exec_splits == 1:
        source_gen('generic_cpu_exec.cc')
    else:
        for i in range(1, exec_splits + 1):
            source_gen('generic_cpu_exec_%d.cc' % i)

    # Actually create the builder.
    sources = [desc, parser_py, micro_asm_py]
    IsaDescBuilder(target=gen, source=sources, env=env)
    return gen
```

**run_parser** function is responsible for initiating the parsing for the target 
architecture. It is invoked when the IsaDescBuilder is called. The ISADescBuilder 
is created through the ISADesc function. In the context of a specific architecture,
the developer's responsibility is simply to call the ISADesc method in the local 
SConscript defined within the target architecture directory. The SConscript for
each architecture supplies details about the input ISA files that should be 
parsed. This information, in the form of a "desc" string, is then utilized by 
passing it to the ISADesc function.

```python
#gem5/src/arch/x86/SConscript

    # Add in files generated by the ISA description.
    isa_desc_files = ISADesc('isa/main.isa')
    for f in isa_desc_files:
        # Add in python file dependencies that won't be caught otherwise
        for pyfile in python_files:
            env.Depends(f, "isa/insts/%s" % pyfile)

```

When you look at the SConscript of the X86 architecture, you will find that it 
passes **isa/main.isa** file to ISADesc function. The file ending with isa files 
are usually used to define ISA of the target architecture. In this example, the 
main.isa file is utilized to include all isa files that need a parsing. 

Additionally, observe that the **isa_parser.py and micro_asm.py** files are 
provided to the ISADescrBuilder. These files contain essential functions and 
classes for utilizing PLY and initializing the parsing process. As depicted in 
the run_parser function, it generates **ISAParser** python class object that 
actually handles ISA parsing utilizing the PLY. Note that this class is defined
in the isa_parser.py file passed to the XX. Also **parse_isa_desc** is invoked
through the ISAParser to initiate the parsing. 

#### ISAParser (isa_parser.py)
The ISAParser class is the most important python class that has two crucial roles
in parsing ISA files. It defines necessary rules for lexer and parser such as 
regular expression for tokenziation and context free grammars for parsing. Since
GEM5 utilizes PLY, the rules should be defined following the PLY's syntax. For 
example, context free grammar required for parsing can be defined as a python 
method that starts with **p_**.
Since the ISAParser and its method to parse the ISA files are utilized 
irrespective of the target architecture, it implies that all architectures 
utilize the same GEM5 DSL to define their respective ISAs. The GEM5 DSL is 
sufficiently adaptable to support the implementation of ISAs for diverse 
architectures, including x86, arm, power, mips, and sparc. As a result, there is
generally no need to introduce additional rules for parsing most of the time.

```python
class ISAParser(Grammar):
    # For Lexer
    # Regular expressions for token matching
    t_LPAREN           = r'\('
    t_RPAREN           = r'\)'
    t_LBRACKET         = r'\['
    t_RBRACKET         = r'\]'
    t_LBRACE           = r'\{'
    t_RBRACE           = r'\}'
    t_LESS             = r'\<'
    t_GREATER          = r'\>'
    t_EQUALS           = r'='
    t_COMMA            = r','
    t_SEMI             = r';'
    t_DOT              = r'\.'
    t_COLON            = r':'
    t_DBLCOLON         = r'::'
    t_ASTERISK         = r'\*'
    ......

    # For Parser
    def p_specification(self, t):
        'specification : opt_defs_and_outputs top_level_decode_block'

        for f in self.splits.keys():
            f.write('\n#endif\n')

        for f in self.files.values(): # close ALL the files;
            f.close() # not doing so can cause compilation to fail

        self.write_top_level_files()

        t[0] = True
    ......

```

Furthermore, the ISAParser class is utilized to instantiate the lexer and parser.
However, you might wonder where is the parser and lexer instance generated from
PLY because there is no relevant attributes defined in the ISAParser class. Note
that it isinherited from Grammar class! Also, this class is closely related with
the parse_isa_desc function of the ISAParser. 

```python
class Grammar(object):
    def __getattr__(self, attr):
        if attr == 'lexers':
            self.lexers = []
            return self.lexers
        
        if attr == 'lex_kwargs':
            self.setupLexerFactory()
            return self.lex_kwargs
        
        if attr == 'yacc_kwargs':
            self.setupParserFactory()
            return self.yacc_kwargs
        
        if attr == 'lex':
            self.lex = ply.lex.lex(module=self, **self.lex_kwargs)
            return self.lex
        
        if attr == 'yacc':
            self.yacc = ply.yacc.yacc(module=self, **self.yacc_kwargs)
            return self.yacc
        
        if attr == 'current_lexer':
            if not self.lexers:
                return None
            return self.lexers[-1][0]
        
        if attr == 'current_source':
            if not self.lexers:
                return '<none>'
            return self.lexers[-1][1]
        
        if attr == 'current_line':
            if not self.lexers:
                return -1
            return self.current_lexer.lineno

    def parse_string(self, data, source='<string>', debug=None, tracking=0):
        if not isinstance(data, string_types):
            raise AttributeError(
                "argument must be a string, was '%s'" % type(f))

        lexer = self.lex.clone()
        lexer.input(data)
        self.lexers.append((lexer, source))

        lrtab = ply.yacc.LRTable()
        lrtab.lr_productions = self.yacc.productions
        lrtab.lr_action = self.yacc.action
        lrtab.lr_goto = self.yacc.goto

        parser = ply.yacc.LRParser(lrtab, self.yacc.errorfunc)
        result = parser.parse(lexer=lexer, debug=debug, tracking=tracking)
        self.lexers.pop()
        return result

```
Actually, the Grammer class provides **parse_string** method that parser the 
passed ISA files utilizing PLY Lexer, Yacc, and Parser. As depicted in the code,
the parse_string accesses lex and yacc attribute of the Grammar class. As these
attributes are not statically defined in the class, it is generated at runtime
when they are accessed through the '__getattr__' function. After generating the 
lexer and parser, parser function of the generated parser will parser the ISA
files and return the result.

```python
    def _parse_isa_desc(self, isa_desc_file):
        '''Read in and parse the ISA description.'''
            
        if isa_desc_file in ISAParser.AlreadyGenerated:
            return
        
        # grab the last three path components of isa_desc_file
        self.filename = '/'.join(isa_desc_file.split('/')[-3:])

        # Read file and (recursively) all included files into a string.
        # PLY requires that the input be in a single string so we have to
        # do this up front.
        isa_desc = self.read_and_flatten(isa_desc_file)
        
        # Initialize lineno tracker
        self.lex.lineno = LineTracker(isa_desc_file)
        
        # Parse.
        self.parse_string(isa_desc)
        
        ISAParser.AlreadyGenerated[isa_desc_file] = None
        
    def parse_isa_desc(self, *args, **kwargs):
        try:
            self._parse_isa_desc(*args, **kwargs)
        except ISAParserError as e:
            print(backtrace(self.fileNameStack))
            print("At %s:" % e.lineno)
            print(e) 
            sys.exit(1)
```

Going back to run_parser function, it invokes the parse_isa_desc function of the
Parser python class. It further invokes the parser_string function from the 
Grammar class and starts parsing ISA files!

#### MicroAssembler (micro_asm.py) <a name="microassembler"></a>
Although the rules defined in the ISAParser class is generally sufficient to 
define ISA of one architecture, it might not be sufficient for specific
architecture such as X86 that utilizes microops to define the macroop syntax. 
Since utilizing macroop and microop at the same time to define ISA is not common,
for example only X86 architecture utilize both, in defining ISA, GEM5 provides 
another class called **MicroAssembler** and appropriate rules to parse the GEM5
DSL used for defining macroops and microops. 


```python
#gem5/src/arch/micro_asm.py

class MicroAssembler(object):
    def (self, macro_type, microops,
        rom = None, rom_macroop_type = None):
        self.lexer = lex.lex()
        self.parser = yacc.yacc()
        self.parser.macro_type = macro_type
        self.parser.macroops = {}
        self.parser.microops = microops
        self.parser.rom = rom
        self.parser.rom_macroop_type = rom_macroop_type
        self.parser.symbols = {}
        self.symbols = self.parser.symbols
```

Similar to ISAParser class, it generates PLY lexer and parser  when the 
MicroAssembler object is instantiated. However, compared to ISAParser that only
requires the path for the output directory for the object instantiating, 
MicroAssembler class  requires additional information associated with the 
macroop and microops. I will explain the why they are necessary and how this 
information will be utilized in marcoop parsing soon

### CFG for ISA Parsing
Before explaining how macroop is parsed, I will go over few crucial rules that 
are necessary for parsing ISA files in most of the time. To understand how GEM5
parses ISA files, the rules defined in the ISAParser python class is crucial. It 
also defines rules for tokenization fur lexer, but will not cover the details 
about lexer in this posting.

```python
#gem5/src/arch/isa_parser.py

   def p_specification(self, t):
       'specification : opt_defs_and_outputs top_level_decode_block'

       for f in self.splits.iterkeys():
           f.write('\n#endif\n')

       for f in self.files.itervalues(): # close ALL the files;
           f.close() # not doing so can cause compilation to fail

       self.write_top_level_files()

       t[0] = True

   # 'opt_defs_and_outputs' is a possibly empty sequence of def and/or
   # output statements. Its productions do the hard work of eventually
   # instantiating a GenCode, which are generally emitted (written to disk)
   # as soon as possible, except for the decode_block, which has to be
   # accumulated into one large function of nested switch/case blocks.
   def p_opt_defs_and_outputs_0(self, t):
       'opt_defs_and_outputs : empty'

   def p_opt_defs_and_outputs_1(self, t):
       'opt_defs_and_outputs : defs_and_outputs'

   def p_defs_and_outputs_0(self, t):
       'defs_and_outputs : def_or_output'

   def p_defs_and_outputs_1(self, t):
       'defs_and_outputs : defs_and_outputs def_or_output'

   # The list of possible definition/output statements.
   # They are all processed as they are seen.
   def p_def_or_output(self, t):
       '''def_or_output : name_decl
                        | def_format
                        | def_bitfield
                        | def_bitfield_struct
                        | def_template
                        | def_operand_types
                        | def_operands
                        | output
                        | global_let
                        | split'''
```

The top rule is the **specification**. It means that content in the all isa files
can be interpreted as specification which can comprise of *opt_defs_and_outputs* 
and *top_level_decode_block*. We will mainly take a look at 'opt_defs_and_outputs'
because it can be further parsed down into macroop and microop blocks. As depicted
in its grammar, it can be further parsed down to another defs_and_outputs and 
another def_or_output block. The *def_or_output_block* is the block that we will
specifically take a look at in detail in few sections.

#### let \{\{ ... \}\};
The *def_or_output_blocks* can be further narrowed down into multiple different 
blocks, but the most important blocks related with defining macroops are starting 
with **let**. 

```python
    def p_global_let(self, t):
        'global_let : LET CODELIT SEMI'
        self.updateExportContext()
        self.exportContext["header_output"] = ''
        self.exportContext["decoder_output"] = ''
        self.exportContext["exec_output"] = ''
        self.exportContext["decode_block"] = ''
        self.exportContext["split"] = self.make_split()
        split_setup = '''
def wrap(func):
    def split(sec):
        globals()[sec + '_output'] += func(sec)
    return split
split = wrap(split)
del wrap
'''                      
        # This tricky setup (immediately above) allows us to just write
        # (e.g.) "split('exec')" in the Python code and the split #ifdef's
        # will automatically be added to the exec_output variable. The inner
        # Python execution environment doesn't know about the split points,
        # so we carefully inject and wrap a closure that can retrieve the
        # next split's #define from the parser and add it to the current
        # emission-in-progress.
        try:
            exec(split_setup+fixPythonIndentation(t[2]), self.exportContext)
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            if debug:
                raise
            error(t.lineno(1), 'In global let block: %s' % exc)
        GenCode(self,
                header_output=self.exportContext["header_output"],
                decoder_output=self.exportContext["decoder_output"],
                exec_output=self.exportContext["exec_output"],
                decode_block=self.exportContext["decode_block"]).emit()
```

When the parser comes across tokens composed of the "let {{ }}" block, it 
triggers the **p_global_let** function. The "let" block plays two vital roles in 
parsing ISA files. Initially, it executes Python code literal to declare the 
Python-based classes necessary for parsing. Subsequently, for generating CPP 
implementations of the ISA, it calls the GenCode function. 

#### GenCode: Generating CPP implementation for ISA
```python
class GenCode(object):
    # Constructor.
    def __init__(self, parser,
                 header_output = '', decoder_output = '', exec_output = '',
                 decode_block = '', has_decode_default = False):
        self.parser = parser
        self.header_output = header_output
        self.decoder_output = decoder_output
        self.exec_output = exec_output
        self.decode_block = decode_block
        self.has_decode_default = has_decode_default

    # Write these code chunks out to the filesystem.  They will be properly
    # interwoven by the write_top_level_files().
    def emit(self):
        if self.header_output:
            self.parser.get_file('header').write(self.header_output)
        if self.decoder_output:
            self.parser.get_file('decoder').write(self.decoder_output)
        if self.exec_output:
            self.parser.get_file('exec').write(self.exec_output)
        if self.decode_block:
            self.parser.get_file('decode_block').write(self.decode_block)
```

NEED EXPLANATION


## Parsing X86 Macroops 
In this section, I will go over how GEM5 parses macroop definitions of X86 
architecture. Regardless of the target architecture, the ISA parsing is initiated
by the same GEM5 provided function **parse_isa_desc** of the ISAParser class. 
Since most of the target architecture defines its ISA with multiple isa files, 
all list of the isa files that needs parsing will be usually specified in one 
isa file called main.isa. 

```python
#gem5/src/arch/x86/isa/main.isa

##include "includes.isa"

namespace X86ISA;

##include "operands.isa"
##include "bitfields.isa"
##include "outputblock.isa"
##include "formats/formats.isa"
##include "microasm.isa"
......
```

Upon opening the x86 architecture's main.isa file, you'll notice the inclusion 
of the microasm.isa file. This might cause confusion for readers anticipating 
isa files associated with macroops. Yet, considering that the X86 macroop is 
composed of one or more microops, assembling the microops to generate macroops 
becomes logical when you recall this relationship.

```python
#gem5/src/arch/x86/isa/microasm.isa

let {
    import sys
    sys.path[0:0] = ["src/arch/x86/isa/"]
    from insts import microcode
    # print microcode
    from micro_asm import MicroAssembler, Rom_Macroop
    mainRom = X86MicrocodeRom('main ROM')
    assembler = MicroAssembler(X86Macroop, microopClasses, mainRom, Rom_Macroop)
    ......
    assembler.symbols["fsw"] = readFpReg("FSW")
    assembler.symbols["fcw"] = readFpReg("FCW")
    assembler.symbols["ftw"] = readFpReg("FTW")
    
    macroopDict = assembler.assemble(microcode)
    
    decoder_output += mainRom.getDefinition()
    header_output += mainRom.getDeclaration()

```

As depicted in the let block, it first instantiates the MicroAssembler object.
[MicroAssembler class](#microassembler) is responsible for parsing X86 macroops.
Parsing a single macroop yields a Python class object that embodies the parsed 
macroop. Therefore, it requires the presence of Python class definitions capable 
of representing a single macroop, specifically, the X86Macroop Python class. 
Furthermore, given that a macroop comprises of multiple microops, details about 
the microops defined in the target architecture must be passed to the 
MicroAssembler, specifically, the microopClasses Python dictionary.


### X86Macroop <a name="x86macroop"></a>
The primary objective in creating an **X86Macroop** instance for a parsed macro
operation is to provide information about the parsed macroop. The macroop parsing
plays a role in collecting all relevant information about the macroop, including 
its microops. It is noteworthy that the X86Macroop Python class provides a method 
named 'add_microop.' Also, the goal of the parsing the macroop is to generate a 
CPP implementation for that macroop, enabling execution by the processor pipeline. 
Therefore, the X86Macroop class provides several relevant functions generating 
CPP Implementations based on the collected information. I'll soon elaborate on 
how this class proves beneficial in the automated generation of CPP 
implementations for macroops.

```python
#gem5/src/arch/x86/isa/macroop.isa
class X86Macroop(Combinational_Macroop):
    def add_microop(self, mnemonic, microop):
        microop.mnemonic = mnemonic
        microop.micropc = len(self.microops)
        self.microops.append(microop)

    ......

    def __init__(self, name):
        super(X86Macroop, self).__init__(name)
        self.directives = {
            "adjust_env" : self.setAdjustEnv,
            "adjust_imm" : self.adjustImm,
            "adjust_disp" : self.adjustDisp,
            "serialize_before" : self.serializeBefore,
            "serialize_after" : self.serializeAfter,
            "function_call" : self.function_call,
            "function_return" : self.function_return
        }
        self.declared = False
        self.adjust_env = ""
        self.init_env = ""
        self.adjust_imm = '''
            uint64_t adjustedImm = IMMEDIATE;
            //This is to pacify gcc in case the immediate isn't used.
            adjustedImm = adjustedImm;
        '''
        self.adjust_disp = '''
            uint64_t adjustedDisp = DISPLACEMENT;
            //This is to pacify gcc in case the displacement isn't used.
            adjustedDisp = adjustedDisp;
        '''
        self.serialize_before = False
        self.serialize_after = False
        self.function_call = False
        self.function_return = False

    def getAllocator(self, env):
        return "new X86Macroop::%s(machInst, %s)" % \
                (self.name, env.getAllocator())
    def getMnemonic(self):
        mnemonic = self.name.lower()
        mnemonic = re.match(r'[^_]*', mnemonic).group(0)
        return mnemonic
    def getDeclaration(self):
        #FIXME This first parameter should be the mnemonic. I need to
        #write some code which pulls that out
        declareLabels = ""
        for (label, microop) in self.labels.items():
            declareLabels += "const static uint64_t label_%s = %d;\n" \
                              % (label, microop.micropc)
        iop = InstObjParams(self.getMnemonic(), self.name, "Macroop",
                {"code" : "",
                 "declareLabels" : declareLabels
                })
        return MacroDeclare.subst(iop);
    def getDefinition(self, env):
        #FIXME This first parameter should be the mnemonic. I need to
        #write some code which pulls that out
        numMicroops = len(self.microops)
        allocMicroops = ''
        micropc = 0
        for op in self.microops:
            flags = ["IsMicroop"]
            if micropc == 0:
                flags.append("IsFirstMicroop")

                if self.serialize_before:
                    flags.append("IsSerializing")
                    flags.append("IsSerializeBefore")

            if micropc == numMicroops - 1:
                flags.append("IsLastMicroop")

                if self.serialize_after:
                    flags.append("IsSerializing")
                    flags.append("IsSerializeAfter")

                if self.function_call:
                    flags.append("IsCall")
                    flags.append("IsUncondControl")
                if self.function_return:
                    flags.append("IsReturn")
                    flags.append("IsUncondControl")
            else:
                flags.append("IsDelayedCommit")

            allocMicroops += \
                "microops[%d] = %s;\n" % \
                (micropc, op.getAllocator(flags))
            micropc += 1
        if env.useStackSize:
            useStackSize = "true"
        else:
            useStackSize = "false"
        if env.memoryInst:
            memoryInst = "true"
        else:
            memoryInst = "false"
        regSize = '''(%s || (env.base == INTREG_RSP && %s) ?
                     env.stackSize :
                     env.dataSize)''' % (useStackSize, memoryInst)
        iop = InstObjParams(self.getMnemonic(), self.name, "Macroop",
                            {"code" : "", "num_microops" : numMicroops,
                             "alloc_microops" : allocMicroops,
                             "adjust_env" : self.adjust_env,
                             "adjust_imm" : self.adjust_imm,
                             "adjust_disp" : self.adjust_disp,
                             "disassembly" : env.disassembly,
                             "regSize" : regSize,
                             "init_env" : self.initEnv})
        return MacroConstructor.subst(iop) + \
               MacroDisassembly.subst(iop);
```


### microopClasses <a name="microopDict"></a>
As one macroop can comprise multiple microops, the process of parsing a macroop 
is intricately connected to parsing the microops that make up the macroop. 
Consequently, the parser needs to be aware of the microops present in the target
architecture. This underscores the importance of passing the **microopClasses** 
Python dictionary to the MicroAssembler.

```python
#src/arch/x86/isa/microops/base.isa

let {
    # This will be populated with mappings between microop mnemonics and
    # the classes that represent them.
    microopClasses = {}
};
```

This Python dictionary containing pairs of microop mnemonic strings and their
corresponding class definitions. It's crucial to highlight that each microop 
operation is expressed as a distinct Python class. The microopClasses dictionary, 
once provided, will be assigned to the 'microops' attribute of the MicroAssembler.
Then how this dictionary is generated?

```python
#gem5/src/arch/x86/isa/microops/limop.isa

let {
    class LimmOp(X86Microop):
    ......
    microopClasses["limm"] = LimmOp                                             
```

As depicted in the code, every isa file defines the classes that can be employed 
to represent a microop. Additionally, it generates an entry to the microopClasses 
dictionary, linking the string identifier of the microop to the corresponding 
class that represents the microop. In the above example, generated dictionary 
in the microopClasses associates string "limm" to class "LimOp".

### assemble function and microcode
Parsing the actual macroop and generating X86Macroop objects for each macroop is 
accomplished by calling the assemble function of the MicroAssembler class.

```python
class MicroAssembler(object):
    ......
    def assemble(self, asm):
        self.parser.parse(asm, lexer=self.lexer)
        macroops = self.parser.macroops
        self.parser.macroops = {}
        return macroops
```

As illustrated in the code, it parses the macroop definitions written in GEM5 DSL
and retrieves the macroops. The macroops returned are Python objects, each being 
an instance of X86Macroop.

```python
#gem5/src/arch/x86/isa/microasm.isa                                             
                                                                                
let {                                                                           
    ......
    macroopDict = assembler.assemble(microcode)                                 
```

It's important to highlight that the assemble function also receives *microcode*. 
Despite the potentially confusing name, it's essential to clarify that 'microcode'
refers to an extensive concatenated Python string containing all **macroop**
definitions in GEM5 DSL syntax. These microcode strings are aggregated from 
individual Python files found in the 'isa/insts' directory, where a
rchitecture-specific macroops are defined.

```python
# src/arch/x86/isa/inst/general_purpose/data_transfer/move.py

microcode = '''

#
# Regular moves
#

def macroop MOV_R_MI {
    limm t1, imm, dataSize=asz
    ld reg, seg, [1, t0, t1]
};

def macroop MOV_MI_R {
    limm t1, imm, dataSize=asz
    st reg, seg, [1, t0, t1]
};
```


As specified in the code, a microcode string is defined for each macroop mnemonic,
encapsulating the macroop definitions implemented in GEM5 DSL. Given that these 
microcode strings are spread across individual ISA files for each macroop, it is
necessary to gather all the microcode strings from multiple ISA files.

```python
#gem5/src/arch/x86/isa/insts/general_purpose/data_transfer/__init__.py

categories = ["conditional_move",
              "move",
              "stack_operations",
              "xchg"]

microcode = ""
for category in categories:
    exec "import %s as cat" % category
    microcode += cat.microcode
 ``` 


Every ISA file defining the macrooperations for the x86 architecture is located 
under the 'src/arch/x86/isa/insts/' directory, categorized based on the 
instruction type. The '__init__.py' file in each category directory collects the 
microcode string from Python files located in that directory. As depicted in the 
code, it specifies the Python files defining the macroop and imports the listed
Python files to import microcode string. These strings are concatanated into the 
microcode string. Consequently, the microcode will have all macroop definitions
implemented in GEM5 DSL. 

### Context-free grammar for def macroop
```python                                                                       
# gem5/src/arch/x86/isa/insts/general_purpose/data_transfer/move.py             
                                                                                
microcode = '''                                                                 
def macroop MOV_R_MI {                                                          
    limm t1, imm, dataSize=asz                                                  
    ld reg, seg, [1, t0, t1]                                                    
};    
```

Upon opening any Python file that defines a macroop, you'll readily observe that 
each macroop definition begins with **def macroop**. Like the previously 
encountered **let** block in ISA parsing, this structure is a component of the 
GEM5 DSL syntax associated with macroop definition. Therefore, corresponding 
CFG should be provided to parse the def macrop block.

```python
#gem5/src/arch/micro_asm.py

# Defines a macroop that is combinationally generated
def p_macroop_def_1(t):
    'macroop_def : DEF MACROOP ID block SEMI'
    try:
        curop = t.parser.macro_type(t[3])
    except TypeError:
        print_error("Error creating macroop object.")
        raise
    for statement in t[4].statements:
        handle_statement(t.parser, curop, statement)
    t.parser.macroops[t[3]] = curop
```

Upon encountering the **def macroop** block during microcode parsing, it invokes 
one of the **p_macroop_def_X** functions depending on the format of the macroop 
block, determined by the tokens within the **def** block. Given that the macroop 
block can assume various formats, the corresponding CFG precisely matching the 
macroop block is invoked. In the specific case we're examining, which is the 
**def macroop MOV_R_MI** block, the **p_macroop_def_1** function will be called.

At line 7, it's noticeable that **t[3]**, representing the mnemonic of the 
currently parsed macroop, is passed to invoke **macro_type**. It's important to
note that the macrop_type attribute of the [MicroAssembler class](#microassembler)
has been set as the **X86Macroop** Python class object. Consequently, 
**t.parser.macro_type(t[3])** translates to **X86Macroop(MOV_R_MI)**, leading to
the invocation of the constructor call for the [X86Macroop object](#x86macroop). 
This implies that whenever a **def macroop** block is encountered during parsing, 
it transforms the **def** block into an instance of the X86Macroop Python object.

### Block token: microops consisting of macroop
You may remember that a single X86Macroop object can encapsulate all the details 
about a specific macroop operation, including its constituent microops. However,
immediately after populating the macroop instance, it lacks information about the
microops composing the current macroop class instance. 

```python
class Block(object):
    def __init__(self):
        self.statements = []

......
# A block of statements
def p_block(t):
    'block : LBRACE statements RBRACE'
    block = Block()
    block.statements = t[2]
    t[0] = block
```

As outlined in the rule for block **p_block**, the parser proceeds to parse the
subsequent statements within the **def macroop** block and translates each microop
operations into the corresponding microop classes. Referring back to the earlier
definition of a macroop, it becomes clear that the 'block' token represents a 
collection of multiple lines of microops, forming a single macroop. In detail,
when the parser encounters the 'block' token, it instantiates the 'block' class
object and subsequently adds the parsed statements (microops in string) to the
**statement** field of the block instance.

```python
def p_statements_0(t):
    'statements : statement'
    if t[1]:
        t[0] = [t[1]]
    else:
        t[0] = []

def p_statements_1(t):
    'statements : statements statement'
    if t[2]:
        t[1].append(t[2])
    t[0] = t[1]

def p_statement(t):
    'statement : content_of_statement end_of_statement'
    t[0] = t[1]

# A statement can be a microop or an assembler directive
def p_content_of_statement_0(t):
    '''content_of_statement : microop
                            | directive'''
    t[0] = t[1]

# Ignore empty statements
def p_content_of_statement_1(t):
    'content_of_statement : '
    pass

# Statements are ended by newlines or a semi colon
def p_end_of_statement(t):
    '''end_of_statement : NEWLINE
                        | SEMI'''
    pass
```


The statement is a string that comprises one or more microoperations. Therefore, 
each microop within the statement needs further parsing, necessitating another
CFG for parsing rules. As depicted in the code, the statements can be further
analyzed as either microop or directives. 

```python
class Statement(object):
    def __init__(self):
        self.is_microop = False
        self.is_directive = False
        self.params = ""

class Microop(Statement):
    def __init__(self):
        super(Microop, self).__init__()
        self.mnemonic = ""
        self.labels = []
        self.is_microop = True

# Different flavors of microop to avoid shift/reduce errors
def p_microop_0(t):
    'microop : labels ID'
    microop = Microop()
    microop.labels = t[1]
    microop.mnemonic = t[2]
    t[0] = microop


def p_microop_3(t):
    'microop : ID PARAMS'
    microop = Microop()
    microop.mnemonic = t[1]
    microop.params = t[2]
    t[0] = microop
```

GEM5 establishes diverse grammar rules for parsing microops in different formats.
For instance, the 'limm t1, imm, dataSize=asz' microop, which is part of the 
MOV_R_MI macroop, conforms to the 'p_microop_3 grammar rule'. When the parser 
comes across a 'microop' statement containing a microop ID (mnemonic) and PARAMS 
(parameters of the microop), it generates a 'Microop' instance. Subsequently, 
the parser assigns the parsed mnemonic and parameters to their respective fields 
within the 'Microop' object.

In the context of PLY, t[0] is used to assign the result of the parsing rule. In 
this case, t[0] = microop means that the parsed result of the 'microop' rule is 
set to the Microop instance created (microop). Therefore, the parsing result of 
the microop will be stored in the statements attribute of the block. Moreover, 
by tracing the call stack of the parsing rules, you can discover its utilization 
within the p_macroop_def_1 rule. Let's take a closer look!

### handle_statements- handling microops
Just like the macroop is converted into a 'X86Macroop' Python object, its microop, 
which is stored in the statements attribute of the block, needs to undergo 
transformation into its respective Python classes.

```python
def p_macroop_def_1(t):                                                         
    'macroop_def : DEF MACROOP ID block SEMI'                                   
    .....
    for statement in t[4].statements:                                           
        handle_statement(t.parser, curop, statement)    
```

Within the macroop parsing function, it iterates through each statement, where 
in this context, statements refer to the microops comprising the macroop. The 
'handle_statement' function is then called for each statement. It's important to 
highlight that this function requires both the 'curop,' which represents the 
currently parsed 'X86Macroop' object, and the 'statement,' which represents an 
individual microop.

```python 
def handle_statement(parser, container, statement):
    if statement.is_microop:
        if statement.mnemonic not in parser.microops.keys():
            raise Exception, "Unrecognized mnemonic: %s" % statement.mnemonic
        parser.symbols["__microopClassFromInsideTheAssembler"] = \
            parser.microops[statement.mnemonic]
        try:
            microop = eval('__microopClassFromInsideTheAssembler(%s)' %
                    statement.params, {}, parser.symbols)
        except:
            print_error("Error creating microop object with mnemonic %s." % \
                    statement.mnemonic)
            raise
        try:
            for label in statement.labels:
                container.labels[label.text] = microop
                if label.is_extern:
                    container.externs[label.text] = microop
            container.add_microop(statement.mnemonic, microop)
        except:
            print_error("Error adding microop.")
            raise
    elif statement.is_directive:
        if statement.name not in container.directives.keys():
            raise Exception, "Unrecognized directive: %s" % statement.name
        parser.symbols["__directiveFunctionFromInsideTheAssembler"] = \
            container.directives[statement.name]
        try:
            eval('__directiveFunctionFromInsideTheAssembler(%s)' %
                    statement.params, {}, parser.symbols)
        except:
            print_error("Error executing directive.")
            print(container.directives)
            raise
    else:
        raise Exception, "Didn't recognize the type of statement", statement
```

Every statement can be categorized as either a 'microop' or a 'directive,' and
the processing of each statement is contingent upon its type. As illustrated in
the code, the [microop dictionary](#microopDict) is employed to look up the Python
class linked to the current microop mnemonic. X86 architecture defines microops 
using the GEM5 DSL, and it is parsed into python corredponding python classses
matching with each microop. I will go over how these microops are implemented 
in GEM5 DSL in the next posting. Anyway, the class retrieved from this dictionary 
is then stored in the symbols attribute of the parser. It's crucial to emphasize 
that the parsed microop's mnemonic field (i.e., 'statement.mnemonic') is utilized 
to identify the corresponding reference to the microop class.

The *eval* statement is employed to create an instance of the microop class. This 
involves utilizing the previously obtained microop class and passing the 
'statement.params' as an argument to the 'eval' function. The argument encompasses
all microop operands that follow a microop mnemonic. For instance, in the 'MOV_R_MI'
macroop definition, the 'limm' microop needs operands 't1, imm, dataSize=asz'.

Before executing the 'eval' function, the microop's operands are initially 
formatted as a string. However, since eval utilizes 'parser.symbols' as its 
**local mapping dictionary**, these string operands undergo transformation into 
code statements comprehensible by the microop classes. For example, the initial
operand 't1' is translated into 'InstRegIndex(NUM_INTREGS+1)' as a result of the 
'eval.' Subsequently, these translated operands are supplied to the constructor 
of the corresponding microop class based on the microop's mnemonic. If you are 
curious about how this translation can happen please refer to [appendix](#appendix) 

```python 
def handle_statement(parser, container, statement):
    if statement.is_microop:
        ......
        try: 
            for label in statement.labels:
                container.labels[label.text] = microop
                if label.is_extern:
                    container.externs[label.text] = microop
            container.add_microop(statement.mnemonic, microop)
        except:
            print_error("Error adding microop.")
            raise
```
The handle_statement function creates Python class objects for parsed microops, 
comprising the macroop. These objects should be incorporated into the Python 
object of the corresponding macroop. In the provided code, the container refers
to the Python object of the macroop, which is an instance of X86Macroop.
After the successful parsing of a macroop, the corresponding macroop container 
is saved in the 'parser.macroops' dictionary. It will be returned to the assemble 
function and stored in the 'macroopDict' attribute.

## Translating parsed macroop into C++ class
>The parsed macroops and its microops are instantiated as Python objects, not 
C++ class instances.
{: .prompt-info }

The parsing outcome produces a Python dictionary containing all the macroop, 
each represented as X86Macroop objects. Additionally, the microops within each 
macroop are instances of Python classes stored within the respective macroop 
object. It is crucial to emphasize that GEM5 necessitates C++ classes to simulate
both macroops and microops, rather than Python objects. Therefore, GEM5 should 
generate CPP implmentations based on the parsed information! Let's delve into 
how the automatic translation of Python objects into C++ classes can be achieved,
using the 'MOV_R_MI' class as an illustrative example.

```python
#gem5/build/X86/arch/x86/generated/decoder-ns.cc.inc

// Inst::MOV(['rAb', 'Ob'],{})

        X86Macroop::MOV_R_MI::MOV_R_MI(
                ExtMachInst machInst, EmulEnv _env)
            : Macroop("mov", machInst, 2, _env)
        {
            ;

                uint64_t adjustedImm = IMMEDIATE;
                //This is to pacify gcc in case the immediate isn't used.
                adjustedImm = adjustedImm;
            ;

                uint64_t adjustedDisp = DISPLACEMENT;
                //This is to pacify gcc in case the displacement isn't used.
                adjustedDisp = adjustedDisp;
            ;
            env.setSeg(machInst);
;

        _numSrcRegs = 0;
        _numDestRegs = 0;
        _numFPDestRegs = 0;
        _numVecDestRegs = 0;
        _numVecElemDestRegs = 0;
        _numVecPredDestRegs = 0;
        _numIntDestRegs = 0;
        _numCCDestRegs = 0;;
            const char *macrocodeBlock = "MOV_R_MI";
            //alloc_microops is the code that sets up the microops
            //array in the parent class.
            microops[0] =
                (env.addressSize >= 4) ?
                    (StaticInstPtr)(new LimmBig(machInst,
                        macrocodeBlock, (1ULL << StaticInst::IsMicroop) | (1ULL << StaticInst::IsFirstMicroop) | (1ULL << StaticInst::IsDelayedCommit), InstRegIndex(NUM_INTREGS+1), adjustedImm,
                        env.addressSize)) :
                    (StaticInstPtr)(new Limm(machInst,
                        macrocodeBlock, (1ULL << StaticInst::IsMicroop) | (1ULL << StaticInst::IsFirstMicroop) | (1ULL << StaticInst::IsDelayedCommit), InstRegIndex(NUM_INTREGS+1), adjustedImm,
                        env.addressSize))
            ;
microops[1] =
                (env.dataSize >= 4) ?
                    (StaticInstPtr)(new LdBig(machInst,
                        macrocodeBlock, (1ULL << StaticInst::IsMicroop) | (1ULL << StaticInst::IsLastMicroop), 1, InstRegIndex(NUM_INTREGS+0),
                        InstRegIndex(NUM_INTREGS+1), 0, InstRegIndex(env.seg), InstRegIndex(env.reg),
                        env.dataSize, env.addressSize, 0 | (machInst.legacy.addr ? (AddrSizeFlagBit << FlagShift) : 0))) :
                    (StaticInstPtr)(new Ld(machInst,
                        macrocodeBlock, (1ULL << StaticInst::IsMicroop) | (1ULL << StaticInst::IsLastMicroop), 1, InstRegIndex(NUM_INTREGS+0),
                        InstRegIndex(NUM_INTREGS+1), 0, InstRegIndex(env.seg), InstRegIndex(env.reg),
                        env.dataSize, env.addressSize, 0 | (machInst.legacy.addr ? (AddrSizeFlagBit << FlagShift) : 0)))
            ;
;
        }
```

The class above is generated automatically. Given that we already possess 
Python-based macroop containers defining the 'MOV_R_MI' macroop, it follows 
logically that the resulting C++ class is derived from the corresponding Python
class. Since all parsed macroop objects are accessible from the 'macroopDict,' 
it would be natural to investigate where the 'macroopDict' is employed to 
comprehend the translation process.

```python
#gem5/src/arch/x86/isa/macroop.isa

let {
    doModRMString = "env.doModRM(machInst);\n"
    noModRMString = "env.setSeg(machInst);\n"
    def genMacroop(Name, env):
        blocks = OutputBlocks()
        if not Name in macroopDict:
            raise Exception, "Unrecognized instruction: %s" % Name
        macroop = macroopDict[Name]
        if not macroop.declared:
            if env.doModRM:
                macroop.initEnv = doModRMString
            else:
                macroop.initEnv = noModRMString
            blocks.header_output = macroop.getDeclaration()
            blocks.decoder_output = macroop.getDefinition(env)
            macroop.declared = True
        blocks.decode_block = "return %s;\n" % macroop.getAllocator(env)
        return blocks
};
```
As illustrated in the provided code, the 'genMacroop' function retrieves the
macroop object associated with the name of a particular macroop. Subsequently, 
it invokes the 'getDeclaration,' 'getDefinition,' and 'getAllocator' functions 
of the obtained macroop object. It is important to note that the object obtained 
in this process is an instance of the 'X86Macroop' Python class, specifically 
linked to the 'MOV_R_MI' macroop.


### getDefinition: generating C++ class definition for macroop 
```python
#gem5/src/arch/x86/isa/macroop.isa
    class X86Macroop(Combinational_Macroop):
        ......
        def getDefinition(self, env):
            numMicroops = len(self.microops)
            allocMicroops = ''
            micropc = 0
            for op in self.microops:
                flags = ["IsMicroop"]
                if micropc == 0:
                    flags.append("IsFirstMicroop")
            
                    if self.serialize_before:
                        flags.append("IsSerializing")
                        flags.append("IsSerializeBefore")
                    
                if micropc == numMicroops - 1:
                    flags.append("IsLastMicroop")

                    if self.serialize_after:
                        flags.append("IsSerializing")
                        flags.append("IsSerializeAfter")
    
                    if self.function_call:
                        flags.append("IsCall")
                        flags.append("IsUncondControl")
                    if self.function_return:
                        flags.append("IsReturn")
                        flags.append("IsUncondControl")
                    if self.control_direct:
                        flags.append("IsDirectControl")
                    if self.control_indirect:
                        flags.append("IsIndirectControl")
                else:
                    flags.append("IsDelayedCommit")
        
                allocMicroops += \
                    "microops[%d] = %s;\n" % \
                    (micropc, op.getAllocator(flags))
                micropc += 1
            if env.useStackSize:
                useStackSize = "true"
            else:
                useStackSize = "false"
            if env.memoryInst:
                memoryInst = "true"
            else:
                memoryInst = "false"
            regSize = '''(%s || (env.base == INTREG_RSP && %s) ?
                         env.stackSize :
                         env.dataSize)''' % (useStackSize, memoryInst)
            iop = InstObjParams(self.getMnemonic(), self.name, "Macroop",
                                {"code" : "", "num_microops" : numMicroops,
                                 "alloc_microops" : allocMicroops,
                                 "adjust_env" : self.adjust_env,
                                 "adjust_imm" : self.adjust_imm,
                                 "adjust_disp" : self.adjust_disp,
                                 "disassembly" : env.disassembly,
                                 "regSize" : regSize,
                                 "init_env" : self.initEnv})
            return MacroConstructor.subst(iop) + \
                   MacroDisassembly.subst(iop);
```

The primary objective of the getDefinition function is to produce the CPP class
implementation for the macroop. In the context of X86, the semantics of a macroop 
are defined by the microops that compose it. Consequently, it is essential for 
the macroop's constructor to properly initialize its microops consisting of the 
macroop.

>The Python classes representing microops, which together form a macroop, are
>stored in the self.microops attribute of the X86Macroop object
{: .prompt-info }

Considering that a macroop can comprise multiple microops, it is imperative to 
iterate through each Python microop class separately to generate the instantiation 
code for the corresponding C++ microop classes. It's important to highlight that
in the provided code, the variable *op* represents each Python class object of a 
microop constituting the macroop.

Just as each macroop can be translated into a CPP class, all microops are similarly
transformed into CPP. Consequently, to instantiate CPP class objects for the 
**microops** constituting the current macroop, it is necessary to determine which
CPP class of the microops should be instantiated. The code responsible for creating
an instance of each microop CPP class is retrieved from the *getAllocator* method 
of each Python microop class. The resulting code, which instantiates the microops,
is stored in the *allocMicroops* variable.

#### getAllocator: retrieve microop class instantiation code
The *getAllocator* function, within the microop Python class, is responsible for
generating C++ statements that create instances of C++ microop class objects. 
In our specific case, where our interest lies in the Limm microcode of the 
MOV_R_MI macroop, we will delve into how the *getAllocator* function of the 
*LimmOp* class is responsible for generating the corresponding C++ code.

```python
#gem5/src/arch/x86/isa/microops/limmop.isa

106     class LimmOp(X86Microop):
...
116         def getAllocator(self, microFlags):
117             allocString = '''
118                 (%(dataSize)s >= 4) ?
119                     (StaticInstPtr)(new %(class_name)sBig(machInst,
120                         macrocodeBlock, %(flags)s, %(dest)s, %(imm)s,
121                         %(dataSize)s)) :
122                     (StaticInstPtr)(new %(class_name)s(machInst,
123                         macrocodeBlock, %(flags)s, %(dest)s, %(imm)s,
124                         %(dataSize)s))
125             '''
126             allocator = allocString % {
127                 "class_name" : self.className,
128                 "mnemonic" : self.mnemonic,
129                 "flags" : self.microFlagsText(microFlags),
130                 "dest" : self.dest, "imm" : self.imm,
131                 "dataSize" : self.dataSize}
132             return allocator
```

The *getAllocator* function within the LimmOp Python class is responsible for
generating a Python docstring called *allocString*, which includes C++ formatted
code for instantiating microop objects. It's important to note that the string 
contains format specifiers that need to be replaced with the appropriate values 
of the microop. The majority of the substituted content is derived from the 
attributes of the Python microop class. 

When an instance of the LimmOp Python class is created, microop-specific operands
like 'dest' and 'imm' are passed to the constructor of the LimmOp Python class. 
Recall how 'eval' translates the microop's operands and creates the associated 
Python object. For instance, the *className* is set as 'Limm'. It indicates that 
there should be a corresponding 'Limm' C++ class that can be instantiated. The
'Limm' C++ class is also automatically generated by GEM5.

```cpp
//gem5/build/X86/arch/x86/generated/decoder-ns.hh.inc
    class Limm : public X86ISA::X86MicroopBase
    {
      protected:
        const RegIndex dest;
        const uint64_t imm;
        const uint8_t dataSize;
        RegIndex foldOBit;

        std::string generateDisassembly(Addr pc,
            const SymbolTable *symtab) const;

      public:
        Limm(ExtMachInst _machInst,
                const char * instMnem,
                uint64_t setFlags, InstRegIndex _dest,
                uint64_t _imm, uint8_t _dataSize);

        Fault execute(ExecContext *, Trace::InstRecord *) const;
    };
```
For further details about microop, please wait for next posting!

#### Finalize Macroop class definition with template substitution 
```python
#gem5/src/arch/x86/isa/macroop.isa                                              

def template MacroConstructor {
        X86Macroop::%(class_name)s::%(class_name)s(
                ExtMachInst machInst, EmulEnv _env)
            : %(base_class)s("%(mnemonic)s", machInst, %(num_microops)s, _env)
        {
            %(adjust_env)s;
            %(adjust_imm)s;
            %(adjust_disp)s;
            %(init_env)s;
            %(constructor)s;
            const char *macrocodeBlock = "%(class_name)s";
            //alloc_microops is the code that sets up the microops
            //array in the parent class.
            %(alloc_microops)s;
        }       
};         

def template MacroDisassembly {{
    std::string
    X86Macroop::%(class_name)s::generateDisassembly(
            Addr pc, const Loader::SymbolTable *symtab) const
    {
        std::stringstream out;
        out << mnemonic << "\t";

        int regSize = %(regSize)s;
        %(disassembly)s
        // Shut up gcc.
        regSize = regSize;
        return out.str();
    }
}};


    class X86Macroop(Combinational_Macroop): 
            iop = InstObjParams(self.getMnemonic(), self.name, "Macroop",       
                                {"code" : "", "num_microops" : numMicroops,     
                                 "alloc_microops" : allocMicroops,              
                                 "adjust_env" : self.adjust_env,                
                                 "adjust_imm" : self.adjust_imm,                
                                 "adjust_disp" : self.adjust_disp,              
                                 "disassembly" : env.disassembly,               
                                 "regSize" : regSize,                           
                                 "init_env" : self.initEnv})                    
            return MacroConstructor.subst(iop) + \                              
                   MacroDisassembly.subst(iop);         
```

I haven't covered the **def template block** yet, but when you look at the 
automatically generated macroop class definitions in CPP, it will have similar 
code skeleton presented in **MacroConstructor**. It is used for generating CPP 
class for macroop! Based on the passed parameter InstObjParams, it substitutes
the template and generate the CPP code! It's worth noting that the placeholder 
%(alloc_microops)s gets substituted with the constructor code for the microop 
classes that were generated by the previous getAllocator method. The 
MacroDisassembly template is used to automatically introduce member function
*generateDisassembly* to automatically generated macroop class. 
If you are interested in def template block, please bear with me I will explain 
the details of the def template in the next post.


### Appendix
#### Symbols of parser
When discussing the translation of microop's operands, I didn't delve into the 
details of how this translation takes place. As mentioned earlier, 
'parser.symbols' serves as a dictionary that associates particular strings with
corresponding code statements. The string argument of the microop comprises 
operands like 'rax,' 'rbx,' 't1,' 't2,' and so on. However, these operands must
be converted into the appropriate code statements for register references, such
as 'InstRegIndex(NUM_INTREGS+1).' The mapping between one register to code 
referencing it is defined within the 'parser.symbols' dictionary.



```python
#gem5/src/arch/x86/isa/microasm.isa

 61     def regIdx(idx):
 62         return "InstRegIndex(%s)" % idx
 63
 64     assembler.symbols["regIdx"] = regIdx
 65
 66     # Add in symbols for the microcode registers
 67     for num in range(16):
 68         assembler.symbols["t%d" % num] = regIdx("NUM_INTREGS+%d" % num)
 69     for num in range(8):
 70         assembler.symbols["ufp%d" % num] = \
 71             regIdx("FLOATREG_MICROFP(%d)" % num)
 72     # Add in symbols for the segment descriptor registers
 73     for letter in ("C", "D", "E", "F", "G", "H", "S"):
 74         assembler.symbols["%ss" % letter.lower()] = \
 75             regIdx("SEGMENT_REG_%sS" % letter)
 76
 77     # Add in symbols for the various checks of segment selectors.
 78     for check in ("NoCheck", "CSCheck", "CallGateCheck", "IntGateCheck",
 79                   "SoftIntGateCheck", "SSCheck", "IretCheck", "IntCSCheck",
 80                   "TRCheck", "TSSCheck", "InGDTCheck", "LDTCheck"):
 81         assembler.symbols[check] = "Seg%s" % check
 82
 83     for reg in ("TR", "IDTR"):
 84         assembler.symbols[reg.lower()] = regIdx("SYS_SEGMENT_REG_%s" % reg)
 85
 86     for reg in ("TSL", "TSG"):
 87         assembler.symbols[reg.lower()] = regIdx("SEGMENT_REG_%s" % reg)
 88
 89     # Miscellaneous symbols
 90     symbols = {
 91         "reg" : regIdx("env.reg"),
 92         "xmml" : regIdx("FLOATREG_XMM_LOW(env.reg)"),
 93         "xmmh" : regIdx("FLOATREG_XMM_HIGH(env.reg)"),
 94         "regm" : regIdx("env.regm"),
 95         "xmmlm" : regIdx("FLOATREG_XMM_LOW(env.regm)"),
 96         "xmmhm" : regIdx("FLOATREG_XMM_HIGH(env.regm)"),
 97         "mmx" : regIdx("FLOATREG_MMX(env.reg)"),
 98         "mmxm" : regIdx("FLOATREG_MMX(env.regm)"),
 99         "imm" : "adjustedImm",
100         "disp" : "adjustedDisp",
101         "seg" : regIdx("env.seg"),
102         "scale" : "env.scale",
103         "index" : regIdx("env.index"),
104         "base" : regIdx("env.base"),
105         "dsz" : "env.dataSize",
106         "asz" : "env.addressSize",
107         "ssz" : "env.stackSize"
108     }
109     assembler.symbols.update(symbols)
```

As we examine the provided code snippet, which is a component of the symbol 
update process, we can observe that different register is mapped to different 
code that can reference that specific register. These symbols play a crucial 
role in converting strings into actual reference code.


```python
#gem5/src/arch/x86/isa/microops/limop.isa

105 let {
106     class LimmOp(X86Microop):
107         def __init__(self, dest, imm, dataSize="env.dataSize"):
108             self.className = "Limm"
109             self.mnemonic = "limm"
110             self.dest = dest
111             if isinstance(imm, (int, long)):
112                 imm = "ULL(%d)" % imm
113             self.imm = imm
114             self.dataSize = dataSize
115
116         def getAllocator(self, microFlags):
117             allocString = '''
118                 (%(dataSize)s >= 4) ?
119                     (StaticInstPtr)(new %(class_name)sBig(machInst,
120                         macrocodeBlock, %(flags)s, %(dest)s, %(imm)s,
121                         %(dataSize)s)) :
122                     (StaticInstPtr)(new %(class_name)s(machInst,
123                         macrocodeBlock, %(flags)s, %(dest)s, %(imm)s,
124                         %(dataSize)s))
125             '''
126             allocator = allocString % {
127                 "class_name" : self.className,
128                 "mnemonic" : self.mnemonic,
129                 "flags" : self.microFlagsText(microFlags),
130                 "dest" : self.dest, "imm" : self.imm,
131                 "dataSize" : self.dataSize}
132             return allocator
133
134     microopClasses["limm"] = LimmOp
```

It's worth noting that the 'LimmOp' Python class requires three operands, and
the actual microcode of 'MOV_R_MI' provides these three operands when utilizing
the 'limm' microop. As a result of the 'eval' function, the operands of the 
'limm' microop are translated into a format that GEM5 can comprehend and are 
then passed to the '__init__' definition of the 'LimmOp' class.

The 'LimmOp' class object, which corresponds to the 'limm' microop operation 
used to implement the 'MOV_R_MI' macroop, is instantiated. This 'LimmOp' class 
object is subsequently stored within the 'X86Macroop' object of the 'MOV_R_MI' 
instruction, accomplished through the 'add_microop' definition of 'X86Macroop.'


### What class object is used for microop class generation?
It might be anticipated that the parsed microop instructions would be 
instantiated from a class with the same name as the microop mnemonic (microop 
opcode), like 'Ld.' However, upon closer examination, it becomes evident that 
a more general class is associated with the group of microops, and it doesn't 
precisely match the microop mnemonic. For example, in the case of the 'ld' 
microop, the associated template class used is 'LoadOp' instead of 'Ld'.
Similarly, for the 'limm' microop instruction, an 'LimmOp' class will represent
this microop. The explanation for this behavior can be found in the 'let' block.

```python
#gem5/src/arch/x86/isa/microops/limop.isa

let {
    class LimmOp(X86Microop):
        def __init__(self, dest, imm, dataSize="env.dataSize"):
            self.className = "Limm"
            self.mnemonic = "limm"
            self.dest = dest
            if isinstance(imm, (int, long)):
                imm = "ULL(%d)" % imm
            self.imm = imm
            self.dataSize = dataSize

        def getAllocator(self, microFlags):
            allocString = '''
                (%(dataSize)s >= 4) ?
                    (StaticInstPtr)(new %(class_name)sBig(machInst,
                        macrocodeBlock, %(flags)s, %(dest)s, %(imm)s,
                        %(dataSize)s)) :
                    (StaticInstPtr)(new %(class_name)s(machInst,
                        macrocodeBlock, %(flags)s, %(dest)s, %(imm)s,
                        %(dataSize)s))
            '''
            allocator = allocString % {
                "class_name" : self.className,
                "mnemonic" : self.mnemonic,
                "flags" : self.microFlagsText(microFlags),
                "dest" : self.dest, "imm" : self.imm,
                "dataSize" : self.dataSize}
            return allocator

    microopClasses["limm"] = LimmOp
    ......
```

A key takeaway from the 'let' block above is that it associates the class
'LimmOp' with its corresponding mnemonic ('limm') within the Python dictionary 
called 'microopClasses'. Consequently, when the dictionary is queried using a
microop's mnemonic, such as 'limm,' it will return the related Python class, 
'LimmOp.'


[1]: https://www.dabeaz.com/ply/ply.html

---
layout: post
titile: "Macroop to Microops"
categories: GEM5, Microops
---
To understand how the macroop can be translated into the microops
let's first start from the familiar mov instructions in x86 architecture.
*gem5/src/arch/x86/isa/insts/general_purpose/data_transfer/move.py*
```python
{% raw %}
 38 microcode = '''
 39
 40 #
 41 # Regular moves
 42 #
 43
 44 def macroop MOV_R_MI {
 45     limm t1, imm, dataSize=asz
 46     ld reg, seg, [1, t0, t1]
 47 };
 48
 49 def macroop MOV_MI_R {
 50     limm t1, imm, dataSize=asz
 51     st reg, seg, [1, t0, t1]
 52 };
{% endraw %}
```
Because x86 provide different format of mov instructions
depending on the operands,
it defines multiple macroops.
As you can see in the above code,
it defines two macroops for mov instruction,
and they are composed of different microops.

In this post, we will take a look at how the macroop is parsed 
and translated into microop invocations.
Before we delve into the details,
we need to understand some basic tools
required for parsing Gem5 defined macroops. 

## Python-Lex-Yacc(PLY) for macroop parsing
Because GEM5 makes use of domain-specific-languaged 
built on top of python
to provide architecture independent 
grammars for defining macroop and microops,
it shuld be translated to CPP code.

For translation,
GEM5 provides *MicroAssembler* class
that utilizes *lexer and parser* classes provided by 
the *Python-Lex-Yacc(PLY)* package.
Also, lexer and parser requires
tokens, context-free grammar, input file 
to parse GEM5 DSL.
We will take a look at how they are defined and provided.

###MicroAssembler parse macroops
*gem5/src/arch/micro_asm.py*
```python
{% raw %}
484 class MicroAssembler(object):
485
486     def __init__(self, macro_type, microops,
487             rom = None, rom_macroop_type = None):
488         self.lexer = lex.lex()
489         self.parser = yacc.yacc()
490         self.parser.macro_type = macro_type
491         self.parser.macroops = {}
492         self.parser.microops = microops
493         self.parser.rom = rom
494         self.parser.rom_macroop_type = rom_macroop_type
495         self.parser.symbols = {}
496         self.symbols = self.parser.symbols
{% endraw %}
```
The *MicroAssembler* class is a wrapper class 
that contains not only a parser and lexer instance,
but also the architecture specific meta-data 
required for understanding specific ISAs. 

Because we are taking a look at the x86 ISA,
let's find out a source code 
where a X86 MicroAssembler class instance is created.

*gem5/src/arch/x86/isa/microasm.isa*
```python
 52 let {{
 53     import sys
 54     sys.path[0:0] = ["src/arch/x86/isa/"]
 55     from insts import microcode
 56     # print microcode
 57     from micro_asm import MicroAssembler, Rom_Macroop
 58     mainRom = X86MicrocodeRom('main ROM')
 59     assembler = MicroAssembler(X86Macroop, microopClasses, mainRom, Rom_Macroop)
```

As shown on the line 59,
MicroAssembler object is instantiated with several parameters:
X86Macroop, microopClasses, mainRom, Rom_Macroop.

###X86Macroop: container of X86 macroop
*gem5/src/arch/x86/isa/macroop.isa*
```python
{% raw %}
136     class X86Macroop(Combinational_Macroop):
137         def add_microop(self, mnemonic, microop):
138             microop.mnemonic = mnemonic
139             microop.micropc = len(self.microops)
140             self.microops.append(microop)
141         def setAdjustEnv(self, val):
142             self.adjust_env = val
143         def adjustImm(self, val):
144             self.adjust_imm += val
145         def adjustDisp(self, val):
146             self.adjust_disp += val
147         def serializeBefore(self):
148             self.serialize_before = True
149         def serializeAfter(self):
150             self.serialize_after = True
151
152         def function_call(self):
153             self.function_call = True
154         def function_return(self):
155             self.function_return = True
156
157         def __init__(self, name):
158             super(X86Macroop, self).__init__(name)
159             self.directives = {
160                 "adjust_env" : self.setAdjustEnv,
161                 "adjust_imm" : self.adjustImm,
162                 "adjust_disp" : self.adjustDisp,
163                 "serialize_before" : self.serializeBefore,
164                 "serialize_after" : self.serializeAfter,
165                 "function_call" : self.function_call,
166                 "function_return" : self.function_return
167             }
168             self.declared = False
169             self.adjust_env = ""
170             self.init_env = ""
171             self.adjust_imm = '''
172                 uint64_t adjustedImm = IMMEDIATE;
173                 //This is to pacify gcc in case the immediate isn't used.
174                 adjustedImm = adjustedImm;
175             '''
176             self.adjust_disp = '''
177                 uint64_t adjustedDisp = DISPLACEMENT;
178                 //This is to pacify gcc in case the displacement isn't used.
179                 adjustedDisp = adjustedDisp;
180             '''
181             self.serialize_before = False
182             self.serialize_after = False
183             self.function_call = False
184             self.function_return = False
{% endraw %}
```

X86Macroop class defined in python 
contains all information required to 
format X86 macroops.
\XXX {SHOPULD BE SPECIFIED WELL}

Although X86Macroop contains additional functions 
that are used for generating CPP definition and declaration of 
corresponding macroop class,
it will be described soon in the later part of this posting.  




###microopClasses: dictionary of microop class definition
*microopClasses* is a python dictionary 
containing pair of microop mnemonic string and 
class definition associated with the mnemonic.
This dictionary is very important in 
translating macroop to microops 
because it should be looked up
to find microop classes consiting of macroop.
For further details about microop parsing and 
dictionary generation, please refer xxx

Also ROM related code is not the scope of this post.
please refer XXX.

##Parse macroops using MicroAssembler::assemble

*gem5/src/arch/micro_asm.py*
```python
489 class MicroAssembler(object):
490
491     def __init__(self, macro_type, microops,
492             rom = None, rom_macroop_type = None):
493         self.lexer = lex.lex()
494         self.parser = yacc.yacc()
495         self.parser.macro_type = macro_type
496         self.parser.macroops = {}
497         self.parser.microops = microops
498         self.parser.rom = rom
499         self.parser.rom_macroop_type = rom_macroop_type
500         self.parser.symbols = {}
501         self.symbols = self.parser.symbols
502
503     def assemble(self, asm):
504         self.parser.parse(asm, lexer=self.lexer)
505         macroops = self.parser.macroops
506         self.parser.macroops = {}
507         return macroops
```
When we look at the MicroAssembler class once again,
it only has one function definition, *assemble*.
As shown in the line 504,
it parses asm with the help of yacc parser
and generates macroops as a result (shown in line 505).

Before we delve into the parse function,
we have to understand that
yacc parser needs three prerequisites to parse something:
*lex, grammar, input to be parsed.*

###What to parse? microcode implementation of macroops
Then what is the asm input of the assemble function?
*gem5/src/arch/x86/isa/microasm.isa
```python
{% raw %}
222     macroopdict = assembler.assemble(microcode)
223
224     decoder_output += mainrom.getdefinition()
225     header_output += mainrom.getdeclaration()
226 }};
{% endraw %}
```
When we look at the place that assemble function is invoked,
we can easily know that the asm is a microcode.
Because of its confusing name, one can misunderstand 
microcode is a microops;
however, the microcode is an input string 
containing macroop descriptions 
consisting of microcode(microops).

microcode descriptions are collected 
from each isa file 
located in isa/insts directory
(all the macroops are stored in there). 

For each instruction category, 
__init__.py in corresponding directory 
iterates every isa files and collects
microcodes of each macroop.

*gem5/src/arch/x86/isa/insts/general_purpose/data_transfer/__init__.py*
 38 categories = ["conditional_move",
 39               "move",
 40               "stack_operations",
 41               "xchg"]
 42
 43 microcode = ""
 44 for category in categories:
 45     exec "import %s as cat" % category
 46     microcode += cat.microcode


###Lexer definition for tokenization
GEM5 makes use of Domain Specific Language
to define macroops.
Therefore, to translate python-like syntax into CPP statements,
lexer should be able to understand 
keywords defined by the language.
For example, as def keyword in python is translated into function definition,
whenever it encounters def macroop block, 
it should interpret the macroop as another keyword.
And this keyword definition is called as token.  

All the lexer definition required for parsing microcode of macroops
is defined in the gem5/src/arch/micro_asm.py.
Syntax of python lexer is defined in this link
(https://www.dabeaz.com/ply/ply.html#ply_nn0).


###Context-free grammar of Microop
To parse the microcode defining macroops.
it needs to understand syntax of DSL of GEM5,
which defines interpretation of one format to the other.
Therefore, to understand
how the microcode of macroop is translated into CPP code,
we have to look at context-free grammar of it.

Let's assume that we want to parse microcode of MOV_R_MI macroop.

```python
 38 microcode = '''
 39
 40 #
 41 # Regular moves
 42 #
 43
 44 def macroop MOV_R_MI {
 45     limm t1, imm, dataSize=asz
 46     ld reg, seg, [1, t0, t1]
 47 };
```

Although def macroop MOV_R_MI looks like function definition block in python,
it has different syntax that cannot be interpreted by python.
Let's try to understand how the GEM5 DSL context-free grammar interprets 
above microcode definition.

*gem5/src/arc/micro_asm.py*
```python
351 # Defines a macroop that is combinationally generated
352 def p_macroop_def_1(t):
353     'macroop_def : DEF MACROOP ID block SEMI'
354     try:
355         curop = t.parser.macro_type(t[3])
356     except TypeError:
357         print_error("Error creating macroop object.")
358         raise
359     for statement in t[4].statements:
360         handle_statement(t.parser, curop, statement)
361     t.parser.macroops[t[3]] = curop
```
When the *def macroop* block is found,
it invokes one of *p_macroop_def* function
depending on the format of macroop block.
Because macroop block can be formated in different ways,
corresponding context free grammar 
exactly matching with a macroop block will be invoked. 
In this case
we are looking at *def macroop MOV_R_MI* block, so
*p_macroop_def_1* function will be invoked. 

When we look at the line 355,
we can find that t[3], mnemonic of the currently parsed macroop 
is used to reference a class defined in *X86Macroop* namespace.
Remember that parser is an instance of MicroAssembler and 
has assigned *X86Macroop* namespace to macro_type field.

###block token: Actual microcode implementation of macroop
The most important token of this grammar rule is the *block*.
In macroop parsing case,
each block token consists of string 
composed of sequence of microop instructions
which actually defines semantic of macroop.

```python
363 # A block of statements
364 def p_block(t):
365     'block : LBRACE statements RBRACE'
366     block = Block()
367     block.statements = t[2]
368     t[0] = block
```
As shown in the block parsing grammar, 
whenever it encounters block, 
it firstly generates block object instance and 
push the parsed statements to the statement field.

Each block contains statement, and statement can 
contain either microop or directive.
To support this syntax,
it provides below class definitions
(deliberately omit the directive class because we only have interest in
grammar rule required for parsing microop)

```python
 92 class Block(object):
 93     def __init__(self):
 94         self.statements = []
 95
 96 class Statement(object):
 97     def __init__(self):
 98         self.is_microop = False
 99         self.is_directive = False
100         self.params = ""
101
102 class Microop(Statement):
103     def __init__(self):
104         super(Microop, self).__init__()
105         self.mnemonic = ""
106         self.labels = []
107         self.is_microop = True
```

Also, to interpret block as group of statements,
statements as group of microops,
it requires below context-free-grammars.

```python
{% raw %}
376 def p_statements_0(t):
377     'statements : statement'
378     if t[1]:
379         t[0] = [t[1]]
380     else:
381         t[0] = []
382
383 def p_statements_1(t):
384     'statements : statements statement'
385     if t[2]:
386         t[1].append(t[2])
387     t[0] = t[1]
388
389 def p_statement(t):
390     'statement : content_of_statement end_of_statement'
391     t[0] = t[1]
392
393 # A statement can be a microop or an assembler directive
394 def p_content_of_statement_0(t):
395     '''content_of_statement : microop
396                             | directive'''
397     t[0] = t[1]
398
399 # Ignore empty statements
400 def p_content_of_statement_1(t):
401     'content_of_statement : '
402     pass
403
404 # Statements are ended by newlines or a semi colon
405 def p_end_of_statement(t):
406     '''end_of_statement : NEWLINE
407                         | SEMI'''
408     pass
{% endraw %}
```
Let's follow above rules step by step
Statements can be interpreted as statement 
or another statements followed by a statement
(Line 376-387)
Each statement consists of 
content_of_statement and end_of_statement tokens
(shown in the 389-391).

Each content of statement can be a microop or directive 
(shown in the line 394-397).
Because we have interest in the case where 
each statement corresponds to one microop,
let's take a look at microop grammars.

```python
410 # Different flavors of microop to avoid shift/reduce errors
411 def p_microop_0(t):
412     'microop : labels ID'
413     microop = Microop()
414     microop.labels = t[1]
415     microop.mnemonic = t[2]
416     t[0] = microop
...
431
432 def p_microop_3(t):
433     'microop : ID PARAMS'
434     microop = Microop()
435     microop.mnemonic = t[1]
436     microop.params = t[2]
437     t[0] = microop
```

parser provides several microop grammars,
but our case (i.e.,  limm t1, imm, dataSize=asz)
matches with fourth grammar rule, p_microop_3.
Whenever it sees a statement containing a microop
that consists of microop ID(mnemonic) and PARAMS(parameters of microop),
it generates Microop instance 
with mnemonic and params field.

##The handle_statement: parsing macroop definition
Now we have parsed statements that contains microops.
As shown in the line 359-360 of parse function,
it iterates every statement(microop) of statements
and invokes handle_statement function.
Also this function requires curop variable,
macroop class reference retrieved from its mnemonic. 

```python 
126 def handle_statement(parser, container, statement):
127     if statement.is_microop:
128         if statement.mnemonic not in parser.microops.keys():
129             raise Exception, "Unrecognized mnemonic: %s" % statement.mnemonic
130         parser.symbols["__microopClassFromInsideTheAssembler"] = \
131             parser.microops[statement.mnemonic]
132         try:
133             microop = eval('__microopClassFromInsideTheAssembler(%s)' %
134                     statement.params, {}, parser.symbols)
135         except:
136             print_error("Error creating microop object with mnemonic %s." % \
137                     statement.mnemonic)
138             raise
139         try:
140             for label in statement.labels:
141                 container.labels[label.text] = microop
142                 if label.is_extern:
143                     container.externs[label.text] = microop
144             container.add_microop(statement.mnemonic, microop)
145         except:
146             print_error("Error adding microop.")
147             raise
148     elif statement.is_directive:
149         if statement.name not in container.directives.keys():
150             raise Exception, "Unrecognized directive: %s" % statement.name
151         parser.symbols["__directiveFunctionFromInsideTheAssembler"] = \
152             container.directives[statement.name]
153         try:
154             eval('__directiveFunctionFromInsideTheAssembler(%s)' %
155                     statement.params, {}, parser.symbols)
156         except:
157             print_error("Error executing directive.")
158             print(container.directives)
159             raise
160     else:
161         raise Exception, "Didn't recognize the type of statement", statement
```
As each statement can be either microop or directive,
each statement is processed differently 
depending on the statement type. 
Because we are taking a look at microops,
we will focus on first conditional part (127-147).

As shown in the line 130-131,
microop dictionary is used to retrieve a class 
associated with current microop mnemonic,
and the retrieved class is stored as symbol of parser.
Note that parsed microop's mnemonic field(statement.mnemonic) is used 
to find corresponding microop class reference. 

Let's go little bit deep down 
to understand how the statement will be translated into microop.

###What class object is used for microop class generation?
One might expects that 
parsed microop instructions are instantiated from a class 
named as microop mnemonic (microop opcode) such as Ld.

However, 
we can easily find that 
it is general class 
associated with that group of microop
not exactly matching with that microop mnemonic.
For microop ld,
associated template class,
LoadOp class is used instead of Ld.

This is because 
parser.microops is a *microopClasses* 
passed to MicroAssembler instance creation.
Please refer XXX to understand 
what is the microopClasses dictionary.

###Different parameter can be fed to one microop instruction
Following *eval* statement(133-134)
instantiates microop class object
using the retrieved microop class.

Note that *statement.params* variable is passed to the eval.
Because each microops consisting of different macroops
might need different microop arguments,
it needs to be passed to generate correct microop instances.  

This argument contains all the microop operands 
following a microop mnemonic in the microop assembly. 
For example, 
*limm* microop used in MOV_R_MI macroop definition
takes t1, imm, dataSize=asz as its operand.

Before the eval is executed,
microop's operands are formatted as a string
that contains all operands required for instantiating microop object.
However, because eval takes parser.symbol as its 
local mapping dictionary, 
the string operands are translated into 
a code statement that can be interpreted by microop classes.

For example, 
the first operand *t1* 
is translated into 
*InstRegIndex(NUM_INTREGS+1)* 
as a result of eval.
And the translated operands are passed to constructor 
of corresponding microop class.

*gem5/src/arch/x86/isa/microops/limop.isa*
```python
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

Note that it requires three operands,
and actual microcode of MOV_R_MI feeds 
three operands when the limm microop is used.

###symbols of parser
When we talked about microop's operand translation
that retrieves a code statement from the string,
I didn't talk about how the translation happens.

As I mentioned already, 
parser.symbols is a dictionary 
that maps specific string to cpp code statement.
Here, the string argument of microop is 
a user-friendly operands 
such as rax, rbx, t1, t2, etc.
However, it should be translated into
proper register refernce code
such as  InstRegIndex(NUM_INTREGS+1).
The parser.symbols dictionary defines this mapping 

*gem5/src/arch/x86/isa/microasm.isa*
```python
{% raw %}
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
{% endraw %}
```
When we look at the above code, 
which is the part of the symbol update code,
we can find lots of symbols 
that translate string to actual referencing code.
When you cannot understand microop's string operand,
you should look at symbol update code.
 

###Adding microops to macroop object and finishing macroop generation
The generated microop objects are added 
to the macroop object *container*
through the *add_microop* method
(line 139-144).
Note that the container is a macroop class 
that possesses parsed microops. 

Although this long procedure is required for parsing one macroop,
we can describe it as two main procedures:
generating macroop container (curop), 
parsing statements consisting of macroop (microop parsing),
storing generated microop objects to the container.

After successfully parsing one macroop,
the generated macroop container is stored 
in the parser.macroops dictionary
(line 361 of p_macroop_def_1).



#How the CPP formatted classes of macroop are generated? 
Now we have parsed macroop containers and 
its microops objects consisting of each macroop.
Note that we only have *python* dictionary 
that contains all macroop containers.
However, when we look at the generated file 
we can find 
automatically generated CPP class of each macroop
as a result of GEM5 compilation,
Let's take a example MOV_R_MI class.

*gem5/build/X86/arch/x86/generated/decoder-ns.cc.inc*
```python
 28024 // Inst::MOV(['rAb', 'Ob'],{})
 28025
 28026         X86Macroop::MOV_R_MI::MOV_R_MI(
 28027                 ExtMachInst machInst, EmulEnv _env)
 28028             : Macroop("mov", machInst, 2, _env)
 28029         {
 28030             ;
 28031
 28032                 uint64_t adjustedImm = IMMEDIATE;
 28033                 //This is to pacify gcc in case the immediate isn't used.
 28034                 adjustedImm = adjustedImm;
 28035             ;
 28036
 28037                 uint64_t adjustedDisp = DISPLACEMENT;
 28038                 //This is to pacify gcc in case the displacement isn't used.
 28039                 adjustedDisp = adjustedDisp;
 28040             ;
 28041             env.setSeg(machInst);
 28042 ;
 28043
 28044         _numSrcRegs = 0;
 28045         _numDestRegs = 0;
 28046         _numFPDestRegs = 0;
 28047         _numVecDestRegs = 0;
 28048         _numVecElemDestRegs = 0;
 28049         _numVecPredDestRegs = 0;
 28050         _numIntDestRegs = 0;
 28051         _numCCDestRegs = 0;;
 28052             const char *macrocodeBlock = "MOV_R_MI";
 28053             //alloc_microops is the code that sets up the microops
 28054             //array in the parent class.
 28055             microops[0] =
 28056                 (env.addressSize >= 4) ?
 28057                     (StaticInstPtr)(new LimmBig(machInst,
 28058                         macrocodeBlock, (1ULL << StaticInst::IsMicroop) | (1ULL << StaticInst::IsFirstMicroop) | (1ULL << StaticInst::IsDelayedCommit), InstRegIndex(NUM_INTREGS+1), adjustedImm,
 28059                         env.addressSize)) :
 28060                     (StaticInstPtr)(new Limm(machInst,
 28061                         macrocodeBlock, (1ULL << StaticInst::IsMicroop) | (1ULL << StaticInst::IsFirstMicroop) | (1ULL << StaticInst::IsDelayedCommit), InstRegIndex(NUM_INTREGS+1), adjustedImm,
 28062                         env.addressSize))
 28063             ;
 28064 microops[1] =
 28065                 (env.dataSize >= 4) ?
 28066                     (StaticInstPtr)(new LdBig(machInst,
 28067                         macrocodeBlock, (1ULL << StaticInst::IsMicroop) | (1ULL << StaticInst::IsLastMicroop), 1, InstRegIndex(NUM_INTREGS+0),
 28068                         InstRegIndex(NUM_INTREGS+1), 0, InstRegIndex(env.seg), InstRegIndex(env.reg),
 28069                         env.dataSize, env.addressSize, 0 | (machInst.legacy.addr ? (AddrSizeFlagBit << FlagShift) : 0))) :
 28070                     (StaticInstPtr)(new Ld(machInst,
 28071                         macrocodeBlock, (1ULL << StaticInst::IsMicroop) | (1ULL << StaticInst::IsLastMicroop), 1, InstRegIndex(NUM_INTREGS+0),
 28072                         InstRegIndex(NUM_INTREGS+1), 0, InstRegIndex(env.seg), InstRegIndex(env.reg),
 28073                         env.dataSize, env.addressSize, 0 | (machInst.legacy.addr ? (AddrSizeFlagBit << FlagShift) : 0)))
 28074             ;
 28075 ;
 28076         }
```
(Although above code looks terrible, 
it has been generated automatically 
as a result of parsing macroop description)

After the macroop parse through the *assemble* function,
we only had a macroop containers 
stored in macroop dictionary.
How the above cpp class could be generated from there?
Let's take a look at the place where
the generated macroop containers *macroopDict* is used.

*gem5/src/arch/x86/isa/macroop.isa*
```python
333 let {{
334     doModRMString = "env.doModRM(machInst);\n"
335     noModRMString = "env.setSeg(machInst);\n"
336     def genMacroop(Name, env):
337         blocks = OutputBlocks()
338         if not Name in macroopDict:
339             raise Exception, "Unrecognized instruction: %s" % Name
340         macroop = macroopDict[Name]
341         if not macroop.declared:
342             if env.doModRM:
343                 macroop.initEnv = doModRMString
344             else:
345                 macroop.initEnv = noModRMString
346             blocks.header_output = macroop.getDeclaration()
347             blocks.decoder_output = macroop.getDefinition(env)
348             macroop.declared = True
349         blocks.decode_block = "return %s;\n" % macroop.getAllocator(env)
350         return blocks
351 }};
```

As shown in the above code,
*genMacroop* function (line 340) retrieves 
macroop container associated with a name of macroop.
It invokes *getDeclaration*, *getDefinition*, and *getAllocator* functions
through the retrieved macroop container.
Note that retrieved container is an instance of *X86Macroop* python class.

###getDefinition of macroop container: generate class definition automatically
*gem5/src/arch/x86/isa/macroop.isa*
```python
{% raw %}
205         def getDefinition(self, env):
206             #FIXME This first parameter should be the mnemonic. I need to
207             #write some code which pulls that out
208             numMicroops = len(self.microops)
209             allocMicroops = ''
210             micropc = 0
211             for op in self.microops:
212                 flags = ["IsMicroop"]
213                 if micropc == 0:
214                     flags.append("IsFirstMicroop")
215
216                     if self.serialize_before:
217                         flags.append("IsSerializing")
218                         flags.append("IsSerializeBefore")
219
220                 if micropc == numMicroops - 1:
221                     flags.append("IsLastMicroop")
222
223                     if self.serialize_after:
224                         flags.append("IsSerializing")
225                         flags.append("IsSerializeAfter")
226
227                     if self.function_call:
228                         flags.append("IsCall")
229                         flags.append("IsUncondControl")
230                     if self.function_return:
231                         flags.append("IsReturn")
232                         flags.append("IsUncondControl")
233                 else:
234                     flags.append("IsDelayedCommit")
235
236                 allocMicroops += \
237                     "microops[%d] = %s;\n" % \
238                     (micropc, op.getAllocator(flags))
239                 micropc += 1
240             if env.useStackSize:
241                 useStackSize = "true"
242             else:
243                 useStackSize = "false"
244             if env.memoryInst:
245                 memoryInst = "true"
246             else:
247                 memoryInst = "false"
248             regSize = '''(%s || (env.base == INTREG_RSP && %s) ?
249                          env.stackSize :
250                          env.dataSize)''' % (useStackSize, memoryInst)
251             iop = InstObjParams(self.getMnemonic(), self.name, "Macroop",
252                                 {"code" : "", "num_microops" : numMicroops,
253                                  "alloc_microops" : allocMicroops,
254                                  "adjust_env" : self.adjust_env,
255                                  "adjust_imm" : self.adjust_imm,
256                                  "adjust_disp" : self.adjust_disp,
257                                  "disassembly" : env.disassembly,
258                                  "regSize" : regSize,
259                                  "init_env" : self.initEnv})
260             return MacroConstructor.subst(iop) + \
261                    MacroDisassembly.subst(iop);
{% endraw %}
```

Currently, 
we only have interest in generating definition
of the macroop class, so 
we are going to focus on *getDefinition* function.
The goal of getDefinition function is 
generating definition of corresponding macroop.

As we've seen before in assemble function,
all microops 
consisting of this macroop 
were added to the container.
And this microops are maintained in *self.microops*
Because one macroop can consist of multiple microops,
each microop object instance should be iterated 
one by one to initiate corresponding microop class instance
(Line 210-239)

Each microop class instance generation code is retrieved
from the *getAllocator* of each *microop* class, and
the generated code is stored to allocMicroops variable.
(line 236-238).

###getAllocatior of microop in detail
The *getAllocator* function 
invoked through microop not the macroop,
generates CPP statement 
that instantiate microop class object.

Because we already have the corresponding microop classes 
associated with a macroop as a result of assemble,
what we have to do is 
traversing microops and invoking getAllocator function.

Because we have interest in Limm microcode of MOV_R_MI macroop,
we are going to look at getAllocator function
of *LimmOp* class.

*gem5/src/arch/x86/isa/microops/limmop.isa*
```python
{% raw %}
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
{% endraw %}
```

The getAllocator function in LimmOp creates 
python doc string, *allocString* 
that consists of CPP formatted
microop object instantiation code (line 117-125).

However, it contains unfinished part 
that should be replaced by proper string
(line 126-131).
Most of the substituted part is excerpted from the 
microop class field, but 
only the microFlags are passed from as an argument of getAllocator.
This flag indicates property of microop 
such as whether it is the first or last microop of macroop.

###Finalize Macroop class definition with template sbustitution 
Although microop constructions code is the most important part of 
generating definition of macroop in the getDefinition function,
it needs other parts of macroop class should be translated into cpp code.

Because every macroop in X86 is defined through
replacing some part of MacroConstructor template,
each macroop should prepare its own substitution string 
that can retrieve class definition 
of corresponding macroop.

This macroop dependent substitution string is prepared as 
InstObjParams shown in line 251-259 of getDefinition function.
After it prepares substitution string,
by replacing 
*MacroopConstructor* and *MacroDisassembly* template,
it can generate CPP formatted full macroop class definition
(Line 260-261),


*gem5/src/arch/x86/isa/macroop.isa*
```python
{% raw %}
 79 // Basic instruction class declaration template.
100 def template MacroDisassembly {{
101     std::string
102     X86Macroop::%(class_name)s::generateDisassembly(Addr pc,
103             const SymbolTable *symtab) const
104     {
105         std::stringstream out;
106         out << mnemonic << "\t";
107
108         int regSize = %(regSize)s;
109         %(disassembly)s
110         // Shut up gcc.
111         regSize = regSize;
112         return out.str();
113     }
114 }};
115
116 // Basic instruction class constructor template.
117 def template MacroConstructor {{
118         X86Macroop::%(class_name)s::%(class_name)s(
119                 ExtMachInst machInst, EmulEnv _env)
120             : %(base_class)s("%(mnemonic)s", machInst, %(num_microops)s, _env)
121         {
122             %(adjust_env)s;
123             %(adjust_imm)s;
124             %(adjust_disp)s;
125             %(init_env)s;
126             %(constructor)s;
127             const char *macrocodeBlock = "%(class_name)s";
128             //alloc_microops is the code that sets up the microops
129             //array in the parent class.
130             %(alloc_microops)s;
131         }
132 }};
{% endraw %}
```

As shown in the above code,
MacroConstructor generates macroop class definition.
Note that 
%(alloc_microops)s on line 130 is replaced by 
microop class instantiation code.
Note that this code has been generated by 
invocation of getAllocaotr of microops.
And other required initialization statements and 
are generated rest of the substitution
such as %(adjust_env)s.

And the MacroDisassembly template adds 
generateDisassembly method of macroop class. 

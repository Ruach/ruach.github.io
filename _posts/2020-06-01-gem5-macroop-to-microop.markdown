---
layout: post
titile: "Macroop to Microops"
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
macroops and microops. As it is another language, it should be parsed by the 
PLY. Based on the predefined rule, GEM5 converts the macroops and microops
implemented in the predefined DSL into corresponding python classes. To help the
parsing and translation, GEM5 introduces MicroAssembler class which coordinates
PLY lexer and parser.

### MicroAssembler Class <a name="microassembler"></a>
```python
#gem5/src/arch/micro_asm.py

class MicroAssembler(object):
    def __init__(self, macro_type, microops,
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

As depicted in the code, it generates PLY lexer and parser automatically when
the MicroAssembler object is instantiated. However, to parse the GEM5 DSL, it
requires additional information associated with the target architecture. 

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
```

Since we want to translate the macroop implemented with GEM5 DSL into corresponding
python class after the parsing, X86Macroop python class is passed. Additionally,
since the macrooperation comprises more than one microoperation, information of 
the microops defined in the target architecture need to be conveyed to the 
MicroAssembler.

### X86Macroop Python class <a name="x86macroop"></a>
One of the result of parsing of x86 macroop is the instance of X86Macroop class 
dedicated for parsed macroop. 


```python
#gem5/src/arch/x86/isa/macroop.isa
class X86Macroop(Combinational_Macroop):
    def add_microop(self, mnemonic, microop):
        microop.mnemonic = mnemonic
        microop.micropc = len(self.microops)
        self.microops.append(microop)
    def setAdjustEnv(self, val):
        self.adjust_env = val
    def adjustImm(self, val):
        self.adjust_imm += val
    def adjustDisp(self, val):
        self.adjust_disp += val
    def serializeBefore(self):
        self.serialize_before = True
    def serializeAfter(self):
        self.serialize_after = True

    def function_call(self):
        self.function_call = True
    def function_return(self):
        self.function_return = True

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

The primary purpose of generating **X86Macroop** instance for parsed macroop is
to provide an information about the parsed macroop. The end goal of parsing the 
macroop is to generate CPP implementation for that macroop that can be executed
by the processor pipeline. Therefore, macroop defined in DSA format is parsed to
python class, and this python class will be translated into CPP implementation 
at the end. Therefore, GEM5 collects all information about the macroop such as 
microops consisting of the macroop and utilize them to generated CPP class. 
It's worth highlighting that X86Macroop Python class defines a method called 
'add_microop.'

### microopClasses <a name="microopDict"></a>
Since one macroop can consists of multiple microops, parsing one macroop is 
closely related with parsing microops consisting of the macroop. Therefore, 
the assembler should be aware of which microops exists in the target architecture.
That's the reason why **microopClasses** python dictionary is passed to the 
MicroAssembler. 

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

## Paring macroop in action
In this section, I will explain how the MicroAssembler class effectively utilizes
X86Macroop python class and microopClasses dictionary in parsing DSL and generating 
python classes that will be used for automatic CPP code generation. Also, as 
GEM5 makes use of PLY for parsing, I will briefly explain about GEM5 DSL and how
they can be parsed. 

```python
#gem5/src/arch/micro_asm.py
class MicroAssembler(object):

    def __init__(self, macro_type, microops,
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

    def assemble(self, asm):
        self.parser.parse(asm, lexer=self.lexer)
        macroops = self.parser.macroops
        self.parser.macroops = {}
        return macroops
```

Upon revisiting the MicroAssembler class, we find a single function definition 
called assemble. This function processes assembly code using the yacc parser and 
produce macroops as its output. 

## Python Yacc (Lexer + Parser)
To comprehend how GEM5 leverages Yacc for assembly parsing, we need to grasp the 
essential components of the Yacc parser and the metadata required for parsing,
which includes lexer definitions, grammar rules, and the input to be parsed.

### Lexer definition for tokenization
It's important to keep in mind that GEM5 utilizes DSL to define macroops. While
these macroops are implemented with Python-like semantics, they don't conform to
actual Python syntax. Consequently, to convert this Python-like syntax into code 
that a compiler or inrpreter can comprehend, the lexer must be able to recognize
the language-specific keywords defined within the DSL.

To illustrate, just as the def keyword in standard Python syntax translates to a 
function definition, the lexer should be capable of recognizing **macroop** as 
another keyword whenever it encounters def macroop block. In this context, this 
definition of a keyword is referred to as a "token." All the lexer definitions 
necessary for parsing the microcode of macroops are specified in 
'gem5/src/arch/micro_asm.py.' The syntax for the Python lexer can be found in
[here](https://www.dabeaz.com/ply/ply.html#ply_nn0).

### What to parse? microcode implementation of macroops
What is the asm input of the assemble function?

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

Upon inspecting the point where the 'assemble' function is invoked, it becomes 
evident that a microcode is passed to the assemble function. Despite its name 
possibly causing confusion, it is crucial to clarify that 'microcode' is a 
lengthy concatenated python string having all **macroop** definitions in GEM5 DSL
syntax. These microcode strings are collected from individual ISA files located 
in the 'isa/insts' directory, where architecture-specific macroops are defined.
 Each macrooperation string in the 'microcode' corresponds to a single instruction. 


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
encapsulating the macroop definitions implemented in GEM5 DSL. Since the 
microcode strings are distributed across individual ISA files for each macroop, 
all microcode string should be collected from multiple ISA files.

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
microcode string from ISA files located in that directory. As depicted in the 
code, each 'init.py' declares the ISA files in the directory as categories and 
imports microcode from all those specified ISA files, then concatenates the 
strings into the microcode. Consequently, the microcode will have all macroop 
definitions implemented in GEM5 DSL. 


### Context-free grammar for X86 macroop
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
While def macroop MOV_R_MI may resemble a typical function definition block in 
Python, its syntax cannot be interpreted by Python as a function (particularly 
given that MOV_R_MI follows the def macroop). To parse this GEM5 DSL, yacc needs
Context-Free-Grammar (CFG) defining the right syntax of the DSL. CFG allows yacc 
to parse macroop defined in GEM5 DSL and translate them into C++ which GEM5 can
understand. Let's see CFG rule associated with parsing MOV_R_MI macroop.

*gem5/src/arch/micro_asm.py*
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

When the def macroop block is encountered, while parsing the microcode,  it 
calls one of the p_macroop_def_X functions based on the format of the macroop 
block (depending on the tokens within the def block). As the macroop block can 
take various formats, the corresponding context-free grammar matching precisely
with the macroop block is invoked. In this particular case, we are examining the
def macroop MOV_R_MI block, so the p_macroop_def_1 function will be invoked.

On line 355, you can observe that **t[3]**, representing the mnemonic of the 
currently parsed macroop, is passed to the macro_type function of the parser.
Keep in mind that the parser is a member field of the 
[MicroAssembler class](#microassembler), and the **X86Macroop** namespace has 
been assigned to parser.macro_type. Therefore, t.parser.macro_type(t[3]) gets 
translated into **X86Macroop(MOV_R_MI)** which will invoke
the [constructor call for the X86Macroop object](#x86macroop). This means that
whenever a def macroop block is encountered during parsing, it translates the 
def block into initialization code for X86Macroop python object.


### Block token: microops consisting of macroop
You may recall that a single X86Macroop object can encompass all the information
about a specific macroop operation, including its constituent microops. However,
right after the macroop instance is populated, it initially contains no 
information about the microops composing the current macroop class instance. As
indicated in the code snippet on lines 359-360, the parser proceeds to parse the
subsequent statements within the def macroop block and translates each microop 
operation into the corresponding microop classes. As observed in the earlier 
definition of a macroop, it becomes evident that the 'block' token represents a
collection of multiple lines of microops, forming a single macroop.

```python
 92 class Block(object):
 93     def __init__(self):
 94         self.statements = []
 95
......
363 # A block of statements
364 def p_block(t):
365     'block : LBRACE statements RBRACE'
366     block = Block()
367     block.statements = t[2]
368     t[0] = block
```
As demonstrated in the grammar for block parsing, when the parser encounters the
'block' token, it initiates the creation of a 'block' object instance and 
subsequently adds the parsed statements (microops in string) to the 'statement'
field of the block.

```python
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
Each Block object has statement member field, and its entries can be interpreted
as either microop or directive class. The block token grammar consists of two 
braces and one statements. The statements is a string consists of more than one 
microops. Therefore, each microops consisting of the statement should be parsed
further, and another CFG for parsing statements is required.

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

Let's break down the rules outlined above in a step-by-step manner. Firstly, a 
'statements' can be interpreted as a 'statement' or another 'statements' 
followed by a 'statement' (as described in lines 376-387). Each 'statement' 
comprises 'content_of_statement' and 'end_of_statement' tokens (as indicated in
lines 389-391). Each 'content of statement,' can have either a 'microop' or a 
'directive' (as demonstrated in lines 394-397). Given our specific interest in 
cases where each 'statement' corresponds to a single 'microop,' let's delve into
the grammatical rules for 'microop'."

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

GEM5 defines various grammar rules for 'microop,' but our specific case (i.e., 
'limm t1, imm, dataSize=asz') aligns with the 'p_microop_3 grammar rule' When 
the parser encounters a 'microop' statement consisting of microop ID (mnemonic)
and PARAMS (parameters of the microop), it generates a 'Microop' instance. It 
then assigns the parsed mnemonic and parameters to their respective fields 
within the 'Microop' object.

## Translating microops to python class object
Now, we have gained insight into how GEM5 parses a 'def' block that defines a 
'macroop' and translates its statements into 'microop' objects. However, this 
isn't the final step in parsing 'macroops.' Let's revisit the 'p_macroop_def_1'
function. While the 'macroop' is translated into an 'X86Macroop' object, the 
'microops' that make up this 'macroop' have not yet been translated into their 
respective counterparts.


```python
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

In the lines 359-360 of the macroop parsing function, it goes through each 
statement, which in this context refers to the microops making up the macroop, 
and invokes the 'handle_statement' function. It's crucial to emphasize that this
function necessitates both the 'curop,' representing the currently parsed 
'X86Macroop' object, and the 'statement', representing an individual microop.

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

Each statement in the code can be either a 'microop' or a 'directive,' and the 
processing of each statement depends on its type. Since we are currently 
focusing on 'microops,' let's delve into the first conditional part 
(lines 127-147). As depicted in lines 130-131, [microop dictionary](#microopDict) 
is used to look up the class associated with the current microop mnemonic. To 
represent each microops, GEM5 defines python classes representing each microop. 
The class retrieved from this dictionary is stored in the symbol variable of the
parser. It's important to note that the parsed microop's mnemonic field 
(i.e., 'statement.mnemonic') is used to find the corresponding reference to the 
microop class. 

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
rLimmOp' with its corresponding mnemonic ('limm') within the Python dictionary 
called 'microopClasses'. Consequently, when the dictionary is queried using a
microop's mnemonic, such as 'limm,' it will return the related Python class, 
'LimmOp.'

### Microop class instantiation
Following *eval* statement(133-134) instantiates microop class object.

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
```
A microop class object is instantiated using the previously retrieved microop 
class. Notably, the 'statement.params' variable is passed as an argument to the
'eval' function. This step is essential because different microops, may require 
different microop arguments. Therefore, it is imperative to pass these arguments
correctly to create the appropriate microop instances. The 'statement.params' 
argument contains all the microop operands that follow a microop mnemonic. For 
example, the 'limm' microop, as used in the 'MOV_R_MI' macroop definition, 
includes operands such as 't1, imm, dataSize=asz.'

Before the 'eval' function is executed, the microop's operands are initially 
formatted as a string. However, because eval takes parser.symbol as its 
*local mapping dictionary*, these string operands are transformed into code 
statements that can be understood by the microop classes. For instance, the 
first operand 't1' is translated into 'InstRegIndex(NUM_INTREGS+1)' as a result 
of the 'eval'. Subsequently, these translated operands are provided to the 
constructor of the corresponding microop class based on the microop's mnemonic.


*gem5/src/arch/x86/isa/microops/limop.isa*
```python
{% raw %}
105 let {{
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
......
159 }};
{% endraw %}
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

### Symbols of parser
When discussing the translation of microop's operands, I didn't delve into the 
details of how this translation takes place. As mentioned earlier, 
'parser.symbols' serves as a dictionary that associates particular strings with
corresponding code statements. The string argument of the microop comprises 
operands like 'rax,' 'rbx,' 't1,' 't2,' and so on. However, these operands must
be converted into the appropriate code statements for register references, such
as 'InstRegIndex(NUM_INTREGS+1).' The mapping between one register to code 
referencing it is defined within the 'parser.symbols' dictionary.



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

As we examine the provided code snippet, which is a component of the symbol 
update process, we can observe that different register is mapped to different 
code that can reference that specific register. These symbols play a crucial 
role in converting strings into actual reference code.

### Summary: handle_statement adds microop object to macroop object
Let's go back to the handle_statement. 
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
```
It's essential to recall that we have instantiated a microop object ('LimmOp') 
that corresponds to the microop's mnemonic ('limm'). Additionally, to create 
this object, we translated the operands of the 'limm' microop. Another crucial
objective of the 'handle_statement' function is to add the populated microop 
objects to the macroop container, referred to as 'container' in the provided 
code (as seen in lines 139-144).

Although this procedure may seem lengthy, it can be broken down into two primary steps: 
1. Generating the macroop container ('curop').
2. Parsing the statements that constitute the macroop ('microop parsing').
3. Storing the generated microop objects in the container.

Once one macroop has been successfully parsed, the resulting macroop container 
is stored in the 'parser.macroops' dictionary (as indicated in line 361 of 
'p_macroop_def_1').



# Translating parsed macroop into C++ class
>The parsed macroops and its microops are instantiated as Python objects, not 
C++ class instances.
{: .prompt-info }

The parsing result yields a Python dictionary that encompasses all the macroop 
containers, represented as X86Macroop objects. Also, microops comprising of each
macroop are Python class instances stored within the macroop container. It's 
important to note that GEM5 requires C++ classes to represent both macroops and 
microops, not Python objects. Initially, when searching for the C++ counterparts
of these macroops and microops, you cannot locate them. However, after compiling
the code base, these classes can be automatically generated. Let's explore how 
the Python classes can be automatically translated into C++ classes, using the
'MOV_R_MI' class as an example.


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

The above class is automatically generated. Since we already have Python-based
macroop containers defining the 'MOV_R_MI' macroop, we can naturally deduce that 
the generated C++ class is derived from the corresponding Python class.
Therefore, let's examine the part of the code where the generated macroop 
containers, known as 'macroopDict,' are put to use.

*gem5/src/arch/x86/isa/macroop.isa*
```python
{% raw %}
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
{% endraw %}
```

As depicted in the provided code, the 'genMacroop' function (at line 340) 
fetches the macroop container linked to the name of a specific macroop. 
Subsequently, it calls the 'getDeclaration,' 'getDefinition,' and 'getAllocator' 
functions of the acquired macroop container. It's worth emphasizing that the 
container obtained here is an instance of the 'X86Macroop' Python class that is 
associated with the 'MOV_R_MI' macroop.


### getDefinition (X86Macroop): generate C++ class definition for macroop 
*gem5/src/arch/x86/isa/macroop.isa*
```python
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
```

The main purpose of the *getDefinition* function is to define the characteristics 
and behavior of the corresponding macroop in the x86 architecture. In X86, the 
actual semantic of a macroop is determined by the microops that constitute it. 
Therefore, it is crucial for the constructor of the macroop to initialize its
microops properly. 

>All Python microop classes that constitute a macroop are stored within the 
self.microops attribute of the X86Macroop object.
{: .prompt-info }

Given that a macroop may consist of multiple microops, it is necessary to 
iterate through each Python microop class individually to generate the 
instantiation code for the corresponding C++ microop classes (Lines 210-239). 
The code responsible for creating instances of each microop class is obtained 
from the *getAllocator* method of each Python microop class. The resulting code, 
which instantiates the microops, is stored in the *allocMicroops* variable 
(Lines 236-238). Note that the microop *op* in the above code indicates the 
python class object of a microop. 

### getAllocator: retrieve microop class instantiation code
The *getAllocator* function is called from the microop and is responsible for
producing C++ statements that create instances of C++ microop class objects. In
our specific case, where we are interested in the Limm microcode of the MOV_R_MI
macroop, we will examine how *getAllocator* function of the *LimmOp* class can 
generate corresponding C++ code.

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
The *getAllocator* function within the LimmOp Python class generates a Python 
doc string *allocString*, which comprises C++ formatted code for instantiating
microop objects (Lines 117-125). While I haven't covered how GEM5 defines the 
C++ classes for microops in detail, we'll delve into this in the upcoming post.
Note that the string contains format specifier that needs to be replaced with 
the appropriate value of the microop (Lines 126-131). Most of the substituted 
content is derived from the fields of the Python microop class. When an instance 
of the LimmOp Python class is created, microop-specific operands such as 'dest' 
and 'imm' are passed to the constructor of the LimmOp Python class. Recall how 
'eval' translates the microop's operands and creates the associated Python 
object. 

Since the 'allocString' contains all the C++ formatted statements, GEM5 should 
provide the remaining information required to compile the automatically
generated C++ source code. For instance, the *className* has been set as 'Limm,'
which implies that there should be a corresponding 'Limm' C++ class that can be 
instantiated. The 'Limm' C++ class is also automatically declared by GEM5.


*gem5/build/X86/arch/x86/generated/decoder-ns.hh.inc*
```cpp
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

### Finalize Macroop class definition with template substitution 
```cpp
136     class X86Macroop(Combinational_Macroop):                                
137         def add_microop(self, mnemonic, microop):    
            ......
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
```

of the MacroConstructor template. Therefore, each macroop needs to prepare its 
own substitution string, which can retrieve the CPP class definition for the 
corresponding macroop. This substitution string, unique to each macroop, is 
created as **InstObjParams**, as demonstrated in lines 251-259 of the 
getDefinition function.

As GEM5 needs to generate classes for various macroops automatically, it 
prepares string templates that implement most parts of the class. Only the 
macroop specific information should be filled in to the template by simple 
string substitution. The macroop specific information is crafted by the 
*InstObjParams*. It will be used to complete missing macroop-specific parts of 
the *MacroConstructor* and *MacroDisassembly* templates. 

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
As depicted in the code above, the MacroConstructor is responsible for crafting 
the definition of the macroop class. It's worth noting that the placeholder 
%(alloc_microops)s, indicated in line 130, gets substituted with the constructor 
code for the microop classes, which is generated by the getAllocator method in 
the Python equivalent of the microops. The MacroDisassembly template is used to 
automatically introduce member function *generateDisassembly* to automatically 
generated macroop class.

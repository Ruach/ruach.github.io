---
layout: post
titile: "Macroop to Microops"
categories: GEM5, Microops
---

GEM5 requires user to implement bottom line interface functions
to help execution of one instruction 
depending on instruction type.
In this posting, we are going to take a look at 
those bottom lines implmentation 
of the load instruction in x86 architecture.
Also, we will briefly go through 
how the instruction is fetched and executed 
using those interfaces. 

Because we have interest on load instructions,
let's take a look at microops defined for 
load/store instruction. 
Note that the defined microop instructions are not 
x86 macro instructions that are exposed to the user
as an ISA such as ld,st,mov instructions.
A sequence of defined microops can define
internal behavior of one macro instruction.
Therefore, understanding how each microop works 
is same as understanding basic block of processor.


{% raw %}
{% endraw %}


To understand how the macroop can be translated into the microops
let's first start from the familiar mov instructions in x86 architecture.
*gem5/src/arch/x86/isa/insts/general_purpose/data_transfer/move.py*
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
 48
 49 def macroop MOV_MI_R {
 50     limm t1, imm, dataSize=asz
 51     st reg, seg, [1, t0, t1]
 52 };
```
Because x86 provide different format of mov instructions
depending on the operands,
it defines multiple macroops.
As you can see in the above code,
it defines two macroops for mov instruction,
and they are composed of different microops 
depending on the operands.

Note that the semantic used for define macroop to microop translation function
has been wrriten with python syntax.
However, the python code cannot be used by the GEM5,
so it has to be actually translated to the cpp code
that initiates associated microop instruction objects.

For this purpose,
GEM5 provides MicroAssembler classe
that makes use of lexer and parser classes provided by the 
Python-Lex-Yacc(PLY) package.
GEM5 provides architecture independent MicroAssembler 
and correspodning tokens and context-free grammar.

*gem5/src/arch/micro_asm.py*
```python
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
```
The *MicroAssembler* class is a wrapper class 
that contains not only the parser and lexer instances,
but also the architecture specific meta-data 
required for understanding specific ISAs. 

Because we are taking a look at the x86 ISA,
let's find out a source code 
where the MicroAssembler class instance is created.

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

Here, we can find that 
arguments 
X86Macroop, microopClasses, mainRom, Rom_Macroop 
are x86 related meta-data required for parsing.

*X86Macroop* is a class definition
used to instantiate X86 macroops.
The X86Macroop class is defined in gem5/src/arch/x86/isa/macroop.isa file.

*microopClasses* is a python dictionary 
contains pair of
microop mnemonic string and 
class that represent it. 
This dictionary is very important in 
retrieving the micro instructions 
consisting of a macro instruction.
Let's first look at how the microop dictionary can be generated.

*gem5/src/arch/x86/isa/microops/ldstop.isa*
```python
430     def defineMicroLoadOp(mnemonic, code, bigCode='',
431                           mem_flags="0", big=True, nonSpec=False,
432                           implicitStack=False):
433         global header_output
434         global decoder_output
435         global exec_output
436         global microopClasses
437         Name = mnemonic
438         name = mnemonic.lower()
439
440         # Build up the all register version of this micro op
441         iops = [InstObjParams(name, Name, 'X86ISA::LdStOp',
442                               { "code": code,
443                                 "ea_code": calculateEA,
444                                 "memDataSize": "dataSize" })]
445         if big:
446             iops += [InstObjParams(name, Name + "Big", 'X86ISA::LdStOp',
447                                    { "code": bigCode,
448                                      "ea_code": calculateEA,
449                                      "memDataSize": "dataSize" })]
450         for iop in iops:
451             header_output += MicroLdStOpDeclare.subst(iop)
452             decoder_output += MicroLdStOpConstructor.subst(iop)
453             exec_output += MicroLoadExecute.subst(iop)
454             exec_output += MicroLoadInitiateAcc.subst(iop)
455             exec_output += MicroLoadCompleteAcc.subst(iop)
456
457         if implicitStack:
458             # For instructions that implicitly access the stack, the address
459             # size is the same as the stack segment pointer size, not the
460             # address size if specified by the instruction prefix
461             addressSize = "env.stackSize"
462         else:
463             addressSize = "env.addressSize"
464
465         base = LdStOp
466         if big:
467             base = BigLdStOp
468         class LoadOp(base):
469             def __init__(self, data, segment, addr, disp = 0,
470                     dataSize="env.dataSize",
471                     addressSize=addressSize,
472                     atCPL0=False, prefetch=False, nonSpec=nonSpec,
473                     implicitStack=implicitStack, uncacheable=False):
474                 super(LoadOp, self).__init__(data, segment, addr,
475                         disp, dataSize, addressSize, mem_flags,
476                         atCPL0, prefetch, nonSpec, implicitStack, uncacheable)
477                 self.className = Name
478                 self.mnemonic = name
479
480         microopClasses[name] = LoadOp
```
Inside a let block,
*defineMicroLoadOp* provides a template method
which can be utilized for generating microops 
belongs to load operation category.
Note that 
the line 468 defines LoadOp class.
Whenever the defineMicroLoadOp is called,
a pair of LoadOp class reference and the name of microop
is stored in the *microopClasses* dictionary.
Note that microopClasses is a variable passed to
previous initialization of MicroAssembler class.
Also retrieved LoadOp classes
can vary from each other because 
it is defined with different mnemonic and class name
corresponding to one microop definition. 

```python
482     defineMicroLoadOp('Ld', 'Data = merge(Data, Mem, dataSize);',
483                             'Data = Mem & mask(dataSize * 8);')
484     defineMicroLoadOp('Ldis', 'Data = merge(Data, Mem, dataSize);',
485                               'Data = Mem & mask(dataSize * 8);',
486                                implicitStack=True)
487     defineMicroLoadOp('Ldst', 'Data = merge(Data, Mem, dataSize);',
488                               'Data = Mem & mask(dataSize * 8);',
489                       '(StoreCheck << FlagShift)')
490     defineMicroLoadOp('Ldstl', 'Data = merge(Data, Mem, dataSize);',
491                                'Data = Mem & mask(dataSize * 8);',
492                       '(StoreCheck << FlagShift) | Request::LOCKED_RMW',
493                       nonSpec=True)
494
495     defineMicroLoadOp('Ldfp', code='FpData_uqw = Mem', big = False)
```

As a result, 
the above invocations of definedMicroLoadOp function
result in storing <LoadOp class, microop name> pairs
on the microopClasses. 
By providing this dictionary,
parser can know 
which class type should be instantiated 
when a particular microop has been encountered during macroop parsing.

Before we delve into the parser to look at how one macroop can be translated to multiple microops,
let's take a look at the *LoadOp* class as an example 
to understand microop classes.
Because LoadOp class inherits from the base class LdStOp
when it is not a big code,
we will take a look at *LdStOp* class.

```python
295     class LdStOp(X86Microop):
296         def __init__(self, data, segment, addr, disp,
297                 dataSize, addressSize, baseFlags, atCPL0, prefetch, nonSpec,
298                 implicitStack, uncacheable):
299             self.data = data
300             [self.scale, self.index, self.base] = addr
301             self.disp = disp
302             self.segment = segment
303             self.dataSize = dataSize
304             self.addressSize = addressSize
305             self.memFlags = baseFlags
306             if atCPL0:
307                 self.memFlags += " | (CPL0FlagBit << FlagShift)"
308             self.instFlags = ""
309             if prefetch:
310                 self.memFlags += " | Request::PREFETCH"
311                 self.instFlags += " | (1ULL << StaticInst::IsDataPrefetch)"
312             if nonSpec:
313                 self.instFlags += " | (1ULL << StaticInst::IsNonSpeculative)"
314             if uncacheable:
315                 self.instFlags += " | (Request::UNCACHEABLE)"
316             # For implicit stack operations, we should use *not* use the
317             # alternative addressing mode for loads/stores if the prefix is set
318             if not implicitStack:
319                 self.memFlags += " | (machInst.legacy.addr ? " + \
320                                  "(AddrSizeFlagBit << FlagShift) : 0)"
321
322         def getAllocator(self, microFlags):
323             allocator = '''new %(class_name)s(machInst, macrocodeBlock,
324                     %(flags)s, %(scale)s, %(index)s, %(base)s,
325                     %(disp)s, %(segment)s, %(data)s,
326                     %(dataSize)s, %(addressSize)s, %(memFlags)s)''' % {
327                 "class_name" : self.className,
328                 "flags" : self.microFlagsText(microFlags) + self.instFlags,
329                 "scale" : self.scale, "index" : self.index,
330                 "base" : self.base,
331                 "disp" : self.disp,
332                 "segment" : self.segment, "data" : self.data,
333                 "dataSize" : self.dataSize, "addressSize" : self.addressSize,
334                 "memFlags" : self.memFlags}
335             return allocator
```
Because LdStOp class supports memory load operation,
it requires memory address, flags representing privilege operation,
prefetch indicator to support memory prefetch.
Also, to support various cache policy, 
it can have uncacheable parameter. 

##Start to parse macroops with MicroAssembler
Then when actually MicroAssembler starts to parse macroops?
After instantiating MicroAssembler instance,
when *assemble* function is invoked,
it starts to parse asm file with defined tokenizer.
Note that *self.lexer* is an alternative tokenizer
defined in micro_asm.py file.

*gem5/src/arch/x86/isa/microasm.isa*
```python
222     macroopDict = assembler.assemble(microcode)
223
224     decoder_output += mainRom.getDefinition()
225     header_output += mainRom.getDeclaration()
226 }};
```

We can find that *microcode* variable is passed 
to the assemble function.
The microcode variable contains ISA descriptions of macroops 
collected from each isa file located in isa/insts directory. 
For each instruction category, 
__init__.py in corresponding category directory 
iterates every isa files in that directory
and collects
it collects microcode description that consists of macroop.

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

###Context-free grammar of Macroop 
MicroAssembler class makes use of Python-Lex-Yacc(PLY)
to parse the macroops,
we have to look at context-free grammar that defines
semantics of the grammar.

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
362
363 # A block of statements
364 def p_block(t):
365     'block : LBRACE statements RBRACE'
366     block = Block()
367     block.statements = t[2]
368     t[0] = block
```

When the *def macroop* block is encountered during parsing,
it invokes one of *p_macroop_def* function
depending on the format of macroop block.
Because macroop block can be formated in different ways,
corresponding context free grammar 
exactly matching with a macroop block will be invoked. 
In this case
we are looking at *def macroop MOV_R_MI* block,
*p_macroop_def_1* function will be invoked. 
because its context free grammar matches with MOV_R_MI definition.

###The handle_statement parses description of macroop
The most important token of this grammar rule is the *block*.
The block token contains string 
composed of sequence of microop instructions
which actually defines semantic of macroop.
Each statement is retrieved from the block token
and processed by the *handle_statement* function
(line 359-360).

Also, note that handle_statement takes macroop object
that microops are belong to.
To make it short,
the handler_statement function parses the statements 
and creates microops objects that comprise of macroop.
And the generated objects are added to the macroop object as a result. 

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
As shown in the line 130-131,
microop dictionary is used to retrieve a class 
associated with current microop mnemonic,
and the retrieved class is stored as symbol of parser.
And the following eval statement(133-134)
instantiates microop class object.

###Different parameter can be fed to one microop instruction
Note that *statement.params* variable is passed to eval 
to set required argument of instantiating microop object.
This argument contains all the microop operands 
following a microop mnemonic in the microop assembly. 
For example, it contains data, segment, displacement, etc 
required for calculating memory address to read.
Also it can optionally set other operands such as prefetch.
For detail parameter corresponding to sepcific microop,
take a look at the associated microop class such as LdStOp.

For example, 
for two ld microops used in different macroops
can have different microop operands.
For ld microop operation,
LdStOP class is used to generate Ld microop class and 
it receives prefetch as its parameter.
Because most of the ld doesn't belong to prefetch, 
it sets prefetch as false by default.
However, by passing the prefetch memory flag as operand of Ld,
different Ld objects can be created,
and they read memory with different semantics.

*gem5/arch/x86/isa/insts/general_purpose/cache_and_memory_management.py*
```python
 39 def macroop PREFETCH_M
 40 {
 41     ld t0, seg, sib, disp, dataSize=1, prefetch=True
 42 };
```
*gem5/arch/x86/isa/insts/general_purpose/data_transfer/move.py*
```python
 67 def macroop MOV_R_M {
 68     ld reg, seg, sib, disp
 69 };
```
*gem5/arch/x86/isa/microops/ldstop.idsa*
```python
294 let {{
295     class LdStOp(X86Microop):
296         def __init__(self, data, segment, addr, disp,
297                 dataSize, addressSize, baseFlags, atCPL0, prefetch, nonSpec,
298                 implicitStack, uncacheable):
299             self.data = data
300             [self.scale, self.index, self.base] = addr
301             self.disp = disp
302             self.segment = segment
303             self.dataSize = dataSize
304             self.addressSize = addressSize
305             self.memFlags = baseFlags
306             if atCPL0:
307                 self.memFlags += " | (CPL0FlagBit << FlagShift)"
308             self.instFlags = ""
309             if prefetch:
310                 self.memFlags += " | Request::PREFETCH"
311                 self.instFlags += " | (1ULL << StaticInst::IsDataPrefetch)"
```


###What class object is used for microop class generation?
One might expects that generated microop object
is instantiated from a class 
representing current microop mnemonic (microop opcode) such as Ld.
However, 
you can easily find that 
it is general class associated with that group of microop
not exactly matching with that microop mnemonic.
For example, if microop is ld,
associated template class, LoadOp class is used.

Now, 
we have a microop object 
generated as a result of statement parsing.
The generated objects are added to the macroop object container 
through the *add_microop* method of *X86Microop* class
(line 144).

This procedure should be iterated number of statement times 
to parse microops comprising of the macroop.
After parsing and adding microops to the macroop object,
the finalized macroop object should be inserted 
to the *parser.macroops* dictionary attribute.

##Who actually translates the parsed macroop to classes?
Now we have parsed macroop objects.
However, when we look at the generated file 
as a result of GEM5 compilation,
we can find that each generated macroop class 
includes microop class objects.
Then which code automatically generates below 
class representing MOV_R_MI macroop? 

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

To figure out how the cpp classes are automatically generated,
we should look at the place that makes use of 
our python dictionary containing macroop objects 
*macroopDict*.

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
*genMacroop* function retrieves macroop class 
associated with a name of macroop
and invokes *getDeclaration & getDefinition* functions.
Those two functions are defined in the X86Macroop class.

###templates are used to generate classes automatically
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
We have only interest in a function that generates definition
of the macroop class, so 
we are going to focus on *getDefinition* function.
The goal of getDefinition function is 
generating definition of corresponding macroop.

The definition of the macroop class 
can be retrieved by the 
*MacroopConstructor and MacroDisassembly template* (line 260-261).
Therefore, getDefinition prepares 
necessary parameters required to substitute the templates.

###microop object instantiation code in macroop class
*alloc_microops* field is one of the most important parameter 
to retrieve actual definition of macroop.
It contains microop definitions that comprise one macroop.
Note that those microop definitions comprising the macroop 
already have been parsed and saved by the MicroAssembler parser. 

Because we already know the corresponding microop classes associated with a macroop,
what we have to do is generating statement to instantiate a new microop object.
The getAllocator function invoked through microop not the macroop,
generates CPP statement that instantiate microop class object.

Here, we only have interest in Load operation,
we are going to look at getAllocator function
of *LdStOp* class.

322         def getAllocator(self, microFlags):
323             allocator = '''new %(class_name)s(machInst, macrocodeBlock,
324                     %(flags)s, %(scale)s, %(index)s, %(base)s,
325                     %(disp)s, %(segment)s, %(data)s,
326                     %(dataSize)s, %(addressSize)s, %(memFlags)s)''' % {
327                 "class_name" : self.className,
328                 "flags" : self.microFlagsText(microFlags) + self.instFlags,
329                 "scale" : self.scale, "index" : self.index,
330                 "base" : self.base,
331                 "disp" : self.disp,
332                 "segment" : self.segment, "data" : self.data,
333                 "dataSize" : self.dataSize, "addressSize" : self.addressSize,
334                 "memFlags" : self.memFlags}
335             return allocator

By the way, we need class definition of Ld not the LdStOp class!
Then why we need to look at LdStOp class?
Because whenever *defineMicroLoadOp* is invoked with specific microop name such as ld,
it generates LoadOp class associated with that microop.
Also because LoadOp inherits from LdStOp
that provides generic class for load store operation,
we have to look at LdStOp to understand how the microop classes can be generated automatically.

To support automatic class generation,
each getAllocator function in LdStOp creates 
python doc string 
that consists of CPP microop object instantiation code.
Because Ld microop is associated with LdStOp class,
it ends up instantiating Ld class object.

###macroop class generation with microop allocations
```python
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
```
As shown in the above code,
MacroConstructor generates actual macroop class definition.
%(alloc_microops)s is substituted by the microop class instances 
retrieved by the getAllocator method.






By the way, what happens to the parameter of the microop?
When we look at the microop assembler, 
we can easily find that therer are several non-x86 registers 
have been used such as r1 to r15.
What are those registers?

*gem5/src/arch/x86/isa/microasm.isa*
```python
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
```
To understand how the r1-t15 are translated to actual 
integer type register used by the microop assembler,
we should look at the above code 
that defines regIdx function and symbols field of the MicroAssembler class.
symbols attribute of the MicroAssembler are frequently used 
by the microasm parser to map 
some symbol used in the microopc assembler 
to the actual microarchitecture context
such as registers.

Here, regIdx return a micro architecture register 
indexed by the idx parameter.
Because InstRegIndex retruns corresponding register 
based on the index number passed to the function,
the index number is important
to pinpoint which type of register is required.

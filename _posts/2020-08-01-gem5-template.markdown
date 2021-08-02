---
layout: post
titile: "GEM5 Template to replace code-literal"
categories: GEM5, Microops
---

## Continues on Parser required for parsing macroop and microop
We took a look at essential part of the parser required for
parsing the macroop and their corresponding microops in the previous posting. 
In this posting, we continuously utilize the parser and its 
grammar defined for understanding Domain Specific Language (DSL) of 
GEM5 defining the ISA including macroop and microop. 

*gem5/src/arch/isa_parser.py*
```python
1896     #####################################################################
1897     #
1898     #                                Parser
1899     #
1900     # Every function whose name starts with 'p_' defines a grammar
1901     # rule.  The rule is encoded in the function's doc string, while
1902     # the function body provides the action taken when the rule is
1903     # matched.  The argument to each function is a list of the values
1904     # of the rule's symbols: t[0] for the LHS, and t[1..n] for the
1905     # symbols on the RHS.  For tokens, the value is copied from the
1906     # t.value attribute provided by the lexer.  For non-terminals, the
1907     # value is assigned by the producing rule; i.e., the job of the
1908     # grammar rule function is to set the value for the non-terminal
1909     # on the LHS (by assigning to t[0]).
1910     #####################################################################
1911 
1912     # The LHS of the first grammar rule is used as the start symbol
1913     # (in this case, 'specification').  Note that this rule enforces
1914     # that there will be exactly one namespace declaration, with 0 or
1915     # more global defs/decls before and after it.  The defs & decls
1916     # before the namespace decl will be outside the namespace; those
1917     # after will be inside.  The decoder function is always inside the
1918     # namespace.
1919     def p_specification(self, t):
1920         'specification : opt_defs_and_outputs top_level_decode_block'
1921 
1922         for f in self.splits.iterkeys():
1923             f.write('\n#endif\n')
1924 
1925         for f in self.files.itervalues(): # close ALL the files;
1926             f.close() # not doing so can cause compilation to fail
1927 
1928         self.write_top_level_files()
1929 
1930         t[0] = True
1931 
1932     # 'opt_defs_and_outputs' is a possibly empty sequence of def and/or
1933     # output statements. Its productions do the hard work of eventually
1934     # instantiating a GenCode, which are generally emitted (written to disk)
1935     # as soon as possible, except for the decode_block, which has to be
1936     # accumulated into one large function of nested switch/case blocks.
1937     def p_opt_defs_and_outputs_0(self, t):
1938         'opt_defs_and_outputs : empty'
1939 
1940     def p_opt_defs_and_outputs_1(self, t):
1941         'opt_defs_and_outputs : defs_and_outputs'
1942 
1943     def p_defs_and_outputs_0(self, t):
1944         'defs_and_outputs : def_or_output'
1945 
1946     def p_defs_and_outputs_1(self, t):
1947         'defs_and_outputs : defs_and_outputs def_or_output'
1948 
1949     # The list of possible definition/output statements.
1950     # They are all processed as they are seen.
1951     def p_def_or_output(self, t):
1952         '''def_or_output : name_decl
1953                          | def_format
1954                          | def_bitfield
1955                          | def_bitfield_struct
1956                          | def_template
1957                          | def_operand_types
1958                          | def_operands
1959                          | output
1960                          | global_let
1961                          | split'''
```
Following the documentation, we can easily understand that 
entire large chunk of DSA defining one microarchitecture's ISA consists of 
two main parts: *opt_defs_and_outputs and top_level_decode_block*.
Because we have interest in def blocks and others (e.g., let block)
instead of decode blocks,
Let's take a look at how the opt_defs_and_outputs block will be parsed further
following the grammar rules. 

### Populating Template object instance per def template 
Whenever the *def template* style of definition is encountered during the parsing,
it will matches the below grammar rule and populate Template objects

```python 
2127     def p_def_template(self, t):
2128         'def_template : DEF TEMPLATE ID CODELIT SEMI'
2129         if t[3] in self.templateMap:
2130             print("warning: template %s already defined" % t[3])
2131         self.templateMap[t[3]] = Template(self, t[4])
```

As shown in the grammar rule, 
Template object is instantiated with the code literal 
of the def template block, t[4].
The new Template object will be maintained 
by the templateMap, and its template name (t[3], ID) 
will be used to index the generated Template object 
inside the map. 

```python
 106 ####################
 107 # Template objects.
 108 #
 109 # Template objects are format strings that allow substitution from
 110 # the attribute spaces of other objects (e.g. InstObjParams instances).
 111 
 112 labelRE = re.compile(r'(?<!%)%\(([^\)]+)\)[sd]')
 113 
 114 class Template(object):
 115     def __init__(self, parser, t):
 116         self.parser = parser
 117         self.template = t
 118 
 119     def subst(self, d):
 120         myDict = None
 121 
 122         # Protect non-Python-dict substitutions (e.g. if there's a printf
 123         # in the templated C++ code)
 124         template = self.parser.protectNonSubstPercents(self.template)
 125 
 126         # Build a dict ('myDict') to use for the template substitution.
 127         # Start with the template namespace.  Make a copy since we're
 128         # going to modify it.
 129         myDict = self.parser.templateMap.copy()
 130 
 131         if isinstance(d, InstObjParams):
 132             # If we're dealing with an InstObjParams object, we need
 133             # to be a little more sophisticated.  The instruction-wide
 134             # parameters are already formed, but the parameters which
 135             # are only function wide still need to be generated.
 136             compositeCode = ''
 137 
 138             myDict.update(d.__dict__)
 139             # The "operands" and "snippets" attributes of the InstObjParams
 140             # objects are for internal use and not substitution.
 141             del myDict['operands']
 142             del myDict['snippets']
 143 
 144             snippetLabels = [l for l in labelRE.findall(template)
 145                              if l in d.snippets]
 146 
 147             snippets = dict([(s, self.parser.mungeSnippet(d.snippets[s]))
 148                              for s in snippetLabels])
 149 
 150             myDict.update(snippets)
 151 
 152             compositeCode = ' '.join(map(str, snippets.values()))
 153 
 154             # Add in template itself in case it references any
 155             # operands explicitly (like Mem)
 156             compositeCode += ' ' + template
 157 
 158             operands = SubOperandList(self.parser, compositeCode, d.operands)
 159 
 160             myDict['op_decl'] = operands.concatAttrStrings('op_decl')
 161             if operands.readPC or operands.setPC:
 162                 myDict['op_decl'] += 'TheISA::PCState __parserAutoPCState;\n'
 163 
 164             # In case there are predicated register reads and write, declare
 165             # the variables for register indicies. It is being assumed that
 166             # all the operands in the OperandList are also in the
 167             # SubOperandList and in the same order. Otherwise, it is
 168             # expected that predication would not be used for the operands.
 169             if operands.predRead:
 170                 myDict['op_decl'] += 'uint8_t _sourceIndex = 0;\n'
 171             if operands.predWrite:
 172                 myDict['op_decl'] += 'uint8_t M5_VAR_USED _destIndex = 0;\n'
 173 
 174             is_src = lambda op: op.is_src
 175             is_dest = lambda op: op.is_dest
 176 
 177             myDict['op_src_decl'] = \
 178                       operands.concatSomeAttrStrings(is_src, 'op_src_decl')
 179             myDict['op_dest_decl'] = \
 180                       operands.concatSomeAttrStrings(is_dest, 'op_dest_decl')
 181             if operands.readPC:
 182                 myDict['op_src_decl'] += \
 183                     'TheISA::PCState __parserAutoPCState;\n'
 184             if operands.setPC:
 185                 myDict['op_dest_decl'] += \
 186                     'TheISA::PCState __parserAutoPCState;\n'
 187 
 188             myDict['op_rd'] = operands.concatAttrStrings('op_rd')
 189             if operands.readPC:
 190                 myDict['op_rd'] = '__parserAutoPCState = xc->pcState();\n' + \
 191                                   myDict['op_rd']
 192 
 193             # Compose the op_wb string. If we're going to write back the
 194             # PC state because we changed some of its elements, we'll need to
 195             # do that as early as possible. That allows later uncoordinated
 196             # modifications to the PC to layer appropriately.
 197             reordered = list(operands.items)
 198             reordered.reverse()
 199             op_wb_str = ''
 200             pcWbStr = 'xc->pcState(__parserAutoPCState);\n'
 201             for op_desc in reordered:
 202                 if op_desc.isPCPart() and op_desc.is_dest:
 203                     op_wb_str = op_desc.op_wb + pcWbStr + op_wb_str
 204                     pcWbStr = ''
 205                 else:
 206                     op_wb_str = op_desc.op_wb + op_wb_str
 207             myDict['op_wb'] = op_wb_str
 208 
 209         elif isinstance(d, dict):
 210             # if the argument is a dictionary, we just use it.
 211             myDict.update(d)
 212         elif hasattr(d, '__dict__'):
 213             # if the argument is an object, we use its attribute map.
 214             myDict.update(d.__dict__)
 215         else:
 216             raise TypeError, "Template.subst() arg must be or have dictionary"
 217         return template % myDict
 218 
 219     # Convert to string.
 220     def __str__(self):
 221         return self.template
```
When the Template object is instantiated, 
its code-literal passed from the parser will be stored
in the self.template field of the Template. 
This template field will be used later in the subst method 
to substitute code-literal following the substitution string.

As shown in the subst definition of the Template class,
we can see that it returns template 
substituted with myDict. 
Therefore, the subst function manages 
myDict based on the object passed to the subst 
and replace the template which is the code-literal.
Note that subst function manages myDict dictionary differently 
based on the type of the object passed to the subst function.
When the InstObjParams type of object is passed,
it needs extra manage to generate myDict 
suitable for substituting the template. 


### defineMicroLoadOp: def template example 
Let's take a look at how the *def template* method will be used 
to generate different microop operations.
Mainly, the **subst** method provided by the Template object 
will be used to populated different microop operations.
GEM5 utilize the substitution a lot to populate 
various instructions having similar semantics.

*gem5/src/arch/x86/isa/microops/ldstop.isa*
```python
434 let {{
435 
436     # Make these empty strings so that concatenating onto
437     # them will always work.
438     header_output = ""
439     decoder_output = ""
440     exec_output = ""
441 
442     segmentEAExpr = \
443         'bits(scale * Index + Base + disp, addressSize * 8 - 1, 0);'
444 
445     calculateEA = 'EA = SegBase + ' + segmentEAExpr
446 
447     debuggingEA = \
448         'DPRINTF(X86, "EA:%#x index:%#x base:%#x disp:%#x Segbase:%#x scale:%#x, addressSize:%#x, dataSize: %#x \\n", EA, Index, Base, disp, SegBase, scale, addressSize, dataSize)'
449 
450 
451     def defineMicroLoadOp(mnemonic, code, bigCode='',
452                           mem_flags="0", big=True, nonSpec=False,
453                           implicitStack=False):
454         global header_output
455         global decoder_output
456         global exec_output
457         global microopClasses
458         Name = mnemonic
459         name = mnemonic.lower()
460 
461         # Build up the all register version of this micro op
462         iops = [InstObjParams(name, Name, 'X86ISA::LdStOp',
463                               { "code": code,
464                                 "ea_code": calculateEA,
465                                 "memDataSize": "dataSize" })]
466         if big:
467             iops += [InstObjParams(name, Name + "Big", 'X86ISA::LdStOp',
468                                    { "code": bigCode,
469                                      "ea_code": calculateEA,
470                                      "memDataSize": "dataSize" })]
471         for iop in iops:
472             header_output += MicroLdStOpDeclare.subst(iop)
473             decoder_output += MicroLdStOpConstructor.subst(iop)
474             exec_output += MicroLoadExecute.subst(iop)
475             exec_output += MicroLoadInitiateAcc.subst(iop)
476             exec_output += MicroLoadCompleteAcc.subst(iop)
477 
478         if implicitStack:
479             # For instructions that implicitly access the stack, the address
480             # size is the same as the stack segment pointer size, not the
481             # address size if specified by the instruction prefix
482             addressSize = "env.stackSize"
483         else:
484             addressSize = "env.addressSize"
485 
486         base = LdStOp
487         if big:
488             base = BigLdStOp
489         class LoadOp(base):
490             def __init__(self, data, segment, addr, disp = 0,
491                     dataSize="env.dataSize",
492                     addressSize=addressSize,
493                     atCPL0=False, prefetch=False, nonSpec=nonSpec,
494                     implicitStack=implicitStack,
495                     uncacheable=False, EnTlb=False):
496                 super(LoadOp, self).__init__(data, segment, addr,
497                         disp, dataSize, addressSize, mem_flags,
498                         atCPL0, prefetch, nonSpec, implicitStack,
499                         uncacheable, EnTlb)
500                 self.className = Name
501                 self.mnemonic = name
502 
503         microopClasses[name] = LoadOp
504 
505     defineMicroLoadOp('Ld', 'Data = merge(Data, Mem, dataSize);',
506                             'Data = Mem & mask(dataSize * 8);')
507     defineMicroLoadOp('Ldis', 'Data = merge(Data, Mem, dataSize);',
508                               'Data = Mem & mask(dataSize * 8);',
509                                implicitStack=True)
510     defineMicroLoadOp('Ldst', 'Data = merge(Data, Mem, dataSize);',
511                               'Data = Mem & mask(dataSize * 8);',
512                       '(StoreCheck << FlagShift)')
513     defineMicroLoadOp('Ldstl', 'Data = merge(Data, Mem, dataSize);',
514                                'Data = Mem & mask(dataSize * 8);',
515                       '(StoreCheck << FlagShift) | Request::LOCKED_RMW',
516                       nonSpec=True)
```

As shown on the line 505-516, 
various load microops are populated by invoking 
defineMicroLoadOp python function. 
Because those microops have similar semantics 
which loads data from memory, 
defineMicroLoadOp function generates different 
microop by substituting generic template.
You can find that multiple subst definitions from
multiple templates are invoked
in the line 472-476 to generate actual implementation
of each microop. 
Let's take a look at MicroLoadExecute as an example. 

```python
{% raw %}
 90 def template MicroLoadExecute {{
 91     Fault %(class_name)s::execute(ExecContext *xc,
 92           Trace::InstRecord *traceData) const
 93     {
{% endraw %}
 94         Fault fault = NoFault;
 95         Addr EA;
 96
 97         %(op_decl)s;
 98         %(op_rd)s;
 99         %(ea_code)s;
100         DPRINTF(X86, "%s : %s: The address is %#x\n", instMnem, mnemonic, EA);
101
102         fault = readMemAtomic(xc, traceData, EA, Mem, dataSize, memFlags);
103
104         if (fault == NoFault) {
105             %(code)s;
106         } else if (memFlags & Request::PREFETCH) {
107             // For prefetches, ignore any faults/exceptions.
108             return NoFault;
109         }
110         if(fault == NoFault)
111         {
112             %(op_wb)s;
113         }
114
115         return fault;
116     }
117 }};
```
The above template contains incomplete code-snippets starting with % keyword. 
When the subst function of the corresponding template object is invoked,
all those uncompleted parts will be replaced.
For this replacement, we built the myDict dictionary.
Therefore, during substitution, if it encounters any keyword 
starting with %, it should refer to myDict to retrieve 
proper replacement for that. 


## Method generation required for basic load operation

### execute: modify ExecContext based on instruction
Currently, we have an automatically generated 
class definition and its constructor.
However, 
it cannot make any change 
to the micro architecture state,
which means 
we need a method that can define semantic of a microop.
One of the important method is *execute* 
that actually changes the architecture state
represented by *ExecContext*.

*exec-ns.cc.inc*
```cpp
19101     Fault Ld::execute(ExecContext *xc,
19102           Trace::InstRecord *traceData) const
19103     {
19104         Fault fault = NoFault;
19105         Addr EA;
19106
19107         uint64_t Index = 0;
19108 uint64_t Base = 0;
19109 uint64_t Data = 0;
19110 uint64_t SegBase = 0;
19111 uint64_t Mem;
19112 ;
19113         Index = xc->readIntRegOperand(this, 0);
19114 Base = xc->readIntRegOperand(this, 1);
19115 Data = xc->readIntRegOperand(this, 2);
19116 SegBase = xc->readMiscRegOperand(this, 3);
19117 ;
19118         EA = SegBase + bits(scale * Index + Base + disp, addressSize * 8 - 1, 0);;
19119         DPRINTF(X86, "%s : %s: The address is %#x\n", instMnem, mnemonic, EA);
19120
19121         fault = readMemAtomic(xc, traceData, EA, Mem, dataSize, memFlags);
19122
19123         if (fault == NoFault) {
19124             Data = merge(Data, Mem, dataSize);;
19125         } else if (memFlags & Request::PREFETCH) {
19126             // For prefetches, ignore any faults/exceptions.
19127             return NoFault;
19128         }
19129         if(fault == NoFault)
19130         {
19131
19132
19133         {
19134             uint64_t final_val = Data;
19135             xc->setIntRegOperand(this, 0, final_val);
19136
19137             if (traceData) { traceData->setData(final_val); }
19138         };
19139         }
19140
19141         return fault;
19142     }
```

*gem5/src/arch/x86/memhelpers.hh*
```python
106 static Fault
107 readMemAtomic(ExecContext *xc, Trace::InstRecord *traceData, Addr addr,
108               uint64_t &mem, unsigned dataSize, Request::Flags flags)
109 {
110     memset(&mem, 0, sizeof(mem));
111     Fault fault = xc->readMem(addr, (uint8_t *)&mem, dataSize, flags);
112     if (fault == NoFault) {
113         // If LE to LE, this is a nop, if LE to BE, the actual data ends up
114         // in the right place because the LSBs where at the low addresses on
115         // access. This doesn't work for BE guests.
116         mem = letoh(mem);
117         if (traceData)
118             traceData->setData(mem);
119     }
120     return fault;
121 }
```


*gem5/src/cpu/exec_context.hh*
```cpp
 57 /**
 58  * The ExecContext is an abstract base class the provides the
 59  * interface used by the ISA to manipulate the state of the CPU model.
 60  *
 61  * Register accessor methods in this class typically provide the index
 62  * of the instruction's operand (e.g., 0 or 1), not the architectural
 63  * register index, to simplify the implementation of register
 64  * renaming.  The architectural register index can be found by
 65  * indexing into the instruction's own operand index table.
 66  *
 67  * @note The methods in this class typically take a raw pointer to the
 68  * StaticInst is provided instead of a ref-counted StaticInstPtr to
 69  * reduce overhead as an argument. This is fine as long as the
 70  * implementation doesn't copy the pointer into any long-term storage
 71  * (which is pretty hard to imagine they would have reason to do).
 72  */
 73 class ExecContext {
 74   public:
 75     typedef TheISA::PCState PCState;
 76
 77     using VecRegContainer = TheISA::VecRegContainer;
 78     using VecElem = TheISA::VecElem;
 79     using VecPredRegContainer = TheISA::VecPredRegContainer;
 ...
 226     /**
 227      * @{
 228      * @name Memory Interface
 229      */
 230     /**
 231      * Perform an atomic memory read operation.  Must be overridden
 232      * for exec contexts that support atomic memory mode.  Not pure
 233      * virtual since exec contexts that only support timing memory
 234      * mode need not override (though in that case this function
 235      * should never be called).
 236      */
 237     virtual Fault readMem(Addr addr, uint8_t *data, unsigned int size,
 238             Request::Flags flags,
 239             const std::vector<bool>& byte_enable = std::vector<bool>())
 240     {
 241         panic("ExecContext::readMem() should be overridden\n");
 242     }
```
As mentioned in the comment,
*ExecContext* class is an abstract base class
used to manipulate state of the CPU model. 
Therefore, each CPU model provides concrete interface 
that can actually updates CPU context.
As an example, let's take a loot at simple cpu model.

*gem5/src/cpu/simple/exec_context.hh*
```cpp
 61 class SimpleExecContext : public ExecContext {
 62   protected:
 63     using VecRegContainer = TheISA::VecRegContainer;
 64     using VecElem = TheISA::VecElem;
 65
 66   public:
 67     BaseSimpleCPU *cpu;
 68     SimpleThread* thread;
 69
 70     // This is the offset from the current pc that fetch should be performed
 71     Addr fetchOffset;
 72     // This flag says to stay at the current pc. This is useful for
 73     // instructions which go beyond MachInst boundaries.
 74     bool stayAtPC;
 75
 76     // Branch prediction
 77     TheISA::PCState predPC;
 78
 79     /** PER-THREAD STATS */
 80
 81     // Number of simulated instructions
 82     Counter numInst;
 83     Stats::Scalar numInsts;
 84     Counter numOp;
 85     Stats::Scalar numOps;
 86
 87     // Number of integer alu accesses
 88     Stats::Scalar numIntAluAccesses;
...
437     Fault
438     readMem(Addr addr, uint8_t *data, unsigned int size,
439             Request::Flags flags,
440             const std::vector<bool>& byte_enable = std::vector<bool>())
441         override
442     {
443         assert(byte_enable.empty() || byte_enable.size() == size);
444         return cpu->readMem(addr, data, size, flags, byte_enable);
445     }
```
As shown in the line 437-445,
readMem method is overridden by *SimpleExecContext* class
inherited from ExecContext abstract class.
Because ExecContext is an interface class,
actual memory read operation is done by the corresponding CPU class.
For timing CPU, 
it doesn't make use of execute,
but other autogenerated method to executed ld microop.
 
### InitiateAcc: send memory reference
```python
{% raw %}
119 def template MicroLoadInitiateAcc {{
120     Fault %(class_name)s::initiateAcc(ExecContext * xc,
121             Trace::InstRecord * traceData) const
{% endraw %}
122     {
123         Fault fault = NoFault;
124         Addr EA;
125
126         %(op_decl)s;
127         %(op_rd)s;
128         %(ea_code)s;
129         DPRINTF(X86, "%s : %s: The address is %#x\n", instMnem, mnemonic, EA);
130
131         fault = initiateMemRead(xc, traceData, EA,
132                                 %(memDataSize)s, memFlags);
133
134         return fault;
135     }
136 }};
137
```

All the template code is required to generate load address.
And the generated address is used by initiateMemRead method
to actually access the memory. 
Note that this method receive ExecContext which is a interface to CPU module
and the generated logical address EA.
Also, memory flags such as prefetch are delivered to the memory module.
Remember that *memFlags* are passed to the class 
when the microop is constructed. 

*gem5/build/X86/arch/x86/generated/exec-ns.cc.inc*
```cpp
19144     Fault Ld::initiateAcc(ExecContext * xc,
19145             Trace::InstRecord * traceData) const
19146     {
19147         Fault fault = NoFault;
19148         Addr EA;
19149
19150         uint64_t Index = 0;
19151 uint64_t Base = 0;
19152 uint64_t SegBase = 0;
19153 ;
19154         Index = xc->readIntRegOperand(this, 0);
19155 Base = xc->readIntRegOperand(this, 1);
19156 SegBase = xc->readMiscRegOperand(this, 3);
19157 ;
19158         EA = SegBase + bits(scale * Index + Base + disp, addressSize * 8 - 1, 0);;
19159         DPRINTF(X86, "%s : %s: The address is %#x\n", instMnem, mnemonic, EA);
19160
19161         fault = initiateMemRead(xc, traceData, EA,
19162                                 dataSize, memFlags);
19163
19164         return fault;
19165     }
```

For memory operation, *initiateAcc* is the most important function
that actually initiate memory access. 
initiateAcc invokes initiateMemRead function, and
each CPU class overrides initiateMemRead method.
Before we take a look at the detail implementation,
we have to understand that 
all the CPU specific functions are invoked 
through the interface ExecContext class.

*gem5/src/arch/x86/memhelpers.hh*
```cpp
 45 /// Initiate a read from memory in timing mode.
 46 static Fault
 47 initiateMemRead(ExecContext *xc, Trace::InstRecord *traceData, Addr addr,
 48                 unsigned dataSize, Request::Flags flags)
 49 {
 50     return xc->initiateMemRead(addr, dataSize, flags);
 51 }
```

initiateMemRead helper function defined in x86 arch directory
invokes actual initiateMemRead function
through the *ExecContext* interface.

*gem5/src/cpu/simple/exec_context.hh*
```cpp
447     Fault
448     initiateMemRead(Addr addr, unsigned int size,
449                     Request::Flags flags,
450                     const std::vector<bool>& byte_enable = std::vector<bool>())
451         override
452     {
453         assert(byte_enable.empty() || byte_enable.size() == size);
454         return cpu->initiateMemRead(addr, size, flags, byte_enable);
455     }
```
Because we have interest in timing cpu model,
let's figure how the timing cpu model implements initiateMemRead.

*gem5/src/cpu/simple/timing.cc*
```cpp
 418 Fault
 419 TimingSimpleCPU::initiateMemRead(Addr addr, unsigned size,
 420                                  Request::Flags flags,
 421                                  const std::vector<bool>& byte_enable)
 422 {
 423     SimpleExecContext &t_info = *threadInfo[curThread];
 424     SimpleThread* thread = t_info.thread;
 425
 426     Fault fault;
 427     const int asid = 0;
 428     const Addr pc = thread->instAddr();
 429     unsigned block_size = cacheLineSize();
 430     BaseTLB::Mode mode = BaseTLB::Read;
 431
 432     if (traceData)
 433         traceData->setMem(addr, size, flags);
 434
 435     RequestPtr req = std::make_shared<Request>(
 436         asid, addr, size, flags, dataMasterId(), pc,
 437         thread->contextId());
 438     if (!byte_enable.empty()) {
 439         req->setByteEnable(byte_enable);
 440     }
 441
 442     req->taskId(taskId());
 443
 444     Addr split_addr = roundDown(addr + size - 1, block_size);
 445     assert(split_addr <= addr || split_addr - addr < block_size);
 446
 447     _status = DTBWaitResponse;
 448     if (split_addr > addr) {
 449         RequestPtr req1, req2;
 450         assert(!req->isLLSC() && !req->isSwap());
 451         req->splitOnVaddr(split_addr, req1, req2);
 452
 453         WholeTranslationState *state =
 454             new WholeTranslationState(req, req1, req2, new uint8_t[size],
 455                                       NULL, mode);
 456         DataTranslation<TimingSimpleCPU *> *trans1 =
 457             new DataTranslation<TimingSimpleCPU *>(this, state, 0);
 458         DataTranslation<TimingSimpleCPU *> *trans2 =
 459             new DataTranslation<TimingSimpleCPU *>(this, state, 1);
 460
 461         thread->dtb->translateTiming(req1, thread->getTC(), trans1, mode);
 462         thread->dtb->translateTiming(req2, thread->getTC(), trans2, mode);
 463     } else {
 464         WholeTranslationState *state =
 465             new WholeTranslationState(req, new uint8_t[size], NULL, mode);
 466         DataTranslation<TimingSimpleCPU *> *translation
 467             = new DataTranslation<TimingSimpleCPU *>(this, state);
 468         thread->dtb->translateTiming(req, thread->getTC(), translation, mode);
 469     }
 470
 471     return NoFault;
 472 }
```
This function first handles split memory access 
that needs two memory access requests.
When the memory address is not aligned, and 
the access crosses the memory block boundary,
then it should be handled with two separate memory requests.
Otherwise, it invokes *translateTiming* function defined in data tlb object(dtb).
Note that initiateMemRead doesn't actually bring the data from the memory to cache.
It first check the tlb for virtual to physical mapping, and 
if the mapping doesn't exist,
it initiate translation request to TLB



### completeAcc: execute memory instruction and bring the data
```python
{% raw %}
138 def template MicroLoadCompleteAcc {{
139     Fault %(class_name)s::completeAcc(PacketPtr pkt, ExecContext * xc,
140                                       Trace::InstRecord * traceData) const
{% endraw %}
141     {
142         Fault fault = NoFault;
143
144         %(op_decl)s;
145         %(op_rd)s;
146
147         getMem(pkt, Mem, dataSize, traceData);
148
149         %(code)s;
150
151         if(fault == NoFault)
152         {
153             %(op_wb)s;
154         }
155
156         return fault;
157     }
158 }};
```

```cpp
19167     Fault Ld::completeAcc(PacketPtr pkt, ExecContext * xc,
19168                                       Trace::InstRecord * traceData) const
19169     {
19170         Fault fault = NoFault;
19171
19172         uint64_t Data = 0;
19173 uint64_t Mem;
19174 ;
19175         Data = xc->readIntRegOperand(this, 2);
19176 ;
19177
19178         getMem(pkt, Mem, dataSize, traceData);
19179
19180         Data = merge(Data, Mem, dataSize);;
19181
19182         if(fault == NoFault)
19183         {
19184
19185
19186         {
19187             uint64_t final_val = Data;
19188             xc->setIntRegOperand(this, 0, final_val);
19189
19190             if (traceData) { traceData->setData(final_val); }
19191         };
19192         }
19193
19194         return fault;
19195     }
```
completeAcc function receives the pkt as its parameter.
pkt contains the actual data read from the memory,
so getMem function reads the proper amount of the data 
from the pkt data structure.
Because memory operation reads 64bytes of data at once 
it should be properly feed to the pipeline depending on the data read size.

#CPU pipeline: fetch-decode-execute
Then who makes use of those automatically generated functions of microop?
Each CPU model makes use of the generated methods differently,
so we are going to look at simple/timing cpu model
which is simple one cycle cpu.

Because simple cpu model is one cycle CPU model,
it doesn't implement multiple pipeline stages.
Although it has no pipeline stages,
entire execution process can be represented as 
three separate functions.


###fetch
*gem5/src/cpu/simple/timing.cc*
```cpp
 653 void
 654 TimingSimpleCPU::fetch()
 655 {
 656     // Change thread if multi-threaded
 657     swapActiveThread();
 658
 659     SimpleExecContext &t_info = *threadInfo[curThread];
 660     SimpleThread* thread = t_info.thread;
 661
 662     DPRINTF(SimpleCPU, "Fetch\n");
 663
 664     if (!curStaticInst || !curStaticInst->isDelayedCommit()) {
 665         checkForInterrupts();
 666         checkPcEventQueue();
 667     }
 668
 669     // We must have just got suspended by a PC event
 670     if (_status == Idle)
 671         return;
 672
 673     TheISA::PCState pcState = thread->pcState();
 674     bool needToFetch = !isRomMicroPC(pcState.microPC()) &&
 675                        !curMacroStaticInst;
 676
 677     if (needToFetch) {
 678         _status = BaseSimpleCPU::Running;
 679         RequestPtr ifetch_req = std::make_shared<Request>();
 680         ifetch_req->taskId(taskId());
 681         ifetch_req->setContext(thread->contextId());
 682         setupFetchRequest(ifetch_req);
 683         DPRINTF(SimpleCPU, "Translating address %#x\n", ifetch_req->getVaddr());
 684         thread->itb->translateTiming(ifetch_req, thread->getTC(),
 685                 &fetchTranslation, BaseTLB::Execute);
 686     } else {
 687         _status = IcacheWaitResponse;
 688         completeIfetch(NULL);
 689
 690         updateCycleCounts();
 691         updateCycleCounters(BaseCPU::CPU_STATE_ON);
 692     }
 693 }
```
###decode
Processor can decode the memory blocks as instruction
after the memory has been fetched from the cache or memory.
Because timing simple CPU assume memory access takes more than single cycle,
it wants to be notified
when the requested memory block has been brought to the processor.

```cpp
 846 void
 847 TimingSimpleCPU::IcachePort::ITickEvent::process()
 848 {                                                                                                                                                                                                                                                                                     849     cpu->completeIfetch(pkt);
 850 }
 851
 852 bool
 853 TimingSimpleCPU::IcachePort::recvTimingResp(PacketPtr pkt)
 854 {
 855     DPRINTF(SimpleCPU, "Received fetch response %#x\n", pkt->getAddr());
 856     // we should only ever see one response per cycle since we only
 857     // issue a new request once this response is sunk
 858     assert(!tickEvent.scheduled());
 859     // delay processing of returned data until next CPU clock edge
 860     tickEvent.schedule(pkt, cpu->clockEdge());
 861
 862     return true;
 863 }
```

As a processor is connected to a memory subsystem through the bus,
bus should be programmed to invoke a function
that can handle the fetched instruction, *completeIfetch*.
When IcachePort receive response from 
memory subsystem, 
it schedule event with received packet.
Because it is scheduled to fire at right next cycle, 
it ends up invoking completeIfetch function of the TimingSimpleCPU.



```cpp
 775 void
 776 TimingSimpleCPU::completeIfetch(PacketPtr pkt)
 777 {
 778     SimpleExecContext& t_info = *threadInfo[curThread];
 779
 780     DPRINTF(SimpleCPU, "Complete ICache Fetch for addr %#x\n", pkt ?
 781             pkt->getAddr() : 0);
 782
 783     // received a response from the icache: execute the received
 784     // instruction
 785     assert(!pkt || !pkt->isError());
 786     assert(_status == IcacheWaitResponse);
 787
 788     _status = BaseSimpleCPU::Running;
 789
 790     updateCycleCounts();
 791     updateCycleCounters(BaseCPU::CPU_STATE_ON);
 792
 793     if (pkt)
 794         pkt->req->setAccessLatency();
 795
 796
 797     preExecute();
 798     if (curStaticInst && curStaticInst->isMemRef()) {
 799         // load or store: just send to dcache
 800         Fault fault = curStaticInst->initiateAcc(&t_info, traceData);
 801
 802         // If we're not running now the instruction will complete in a dcache
 803         // response callback or the instruction faulted and has started an
 804         // ifetch
 805         if (_status == BaseSimpleCPU::Running) {
 806             if (fault != NoFault && traceData) {
 807                 // If there was a fault, we shouldn't trace this instruction.
 808                 delete traceData;
 809                 traceData = NULL;
 810             }
 811
 812             postExecute();
 813             // @todo remove me after debugging with legion done
 814             if (curStaticInst && (!curStaticInst->isMicroop() ||
 815                         curStaticInst->isFirstMicroop()))
 816                 instCnt++;
 817             advanceInst(fault);
 818         }
 819     } else if (curStaticInst) {
 820         // non-memory instruction: execute completely now
 821         Fault fault = curStaticInst->execute(&t_info, traceData);
 822
 823         // keep an instruction count
 824         if (fault == NoFault)
 825             countInst();
 826         else if (traceData && !DTRACE(ExecFaulting)) {
 827             delete traceData;
 828             traceData = NULL;
 829         }
 830
 831         postExecute();
 832         // @todo remove me after debugging with legion done
 833         if (curStaticInst && (!curStaticInst->isMicroop() ||
 834                 curStaticInst->isFirstMicroop()))
 835             instCnt++;
 836         advanceInst(fault);
 837     } else {
 838         advanceInst(NoFault);
 839     }
 840
 841     if (pkt) {
 842         delete pkt;
 843     }
 844 }
```
CompleteIfetch instruction consists of four parts:
preExecute, instruction execution, postExecute, and advanceInst.
By the way, although we cannot see any decoding logic
it makes use of curStaticInst to execute fetched instruction.
Who decodes the fetched packet and generate curStaticInst?
that is a *preExecute* function.

*gem5/src/cpu/simple/base.cc*
```cpp
481 void
482 BaseSimpleCPU::preExecute()
483 {
484     SimpleExecContext &t_info = *threadInfo[curThread];
485     SimpleThread* thread = t_info.thread;
486
487     // maintain $r0 semantics
488     thread->setIntReg(ZeroReg, 0);
489 #if THE_ISA == ALPHA_ISA
490     thread->setFloatReg(ZeroReg, 0);
491 #endif // ALPHA_ISA
492
493     // resets predicates
494     t_info.setPredicate(true);
495     t_info.setMemAccPredicate(true);
496
497     // check for instruction-count-based events
498     thread->comInstEventQueue.serviceEvents(t_info.numInst);
499
500     // decode the instruction
501     TheISA::PCState pcState = thread->pcState();
502
503     if (isRomMicroPC(pcState.microPC())) {
504         t_info.stayAtPC = false;
505         curStaticInst = microcodeRom.fetchMicroop(pcState.microPC(),
506                                                   curMacroStaticInst);
507     } else if (!curMacroStaticInst) {
508         //We're not in the middle of a macro instruction
509         StaticInstPtr instPtr = NULL;
510
511         TheISA::Decoder *decoder = &(thread->decoder);
512
513         //Predecode, ie bundle up an ExtMachInst
514         //If more fetch data is needed, pass it in.
515         Addr fetchPC = (pcState.instAddr() & PCMask) + t_info.fetchOffset;
516         //if (decoder->needMoreBytes())
517             decoder->moreBytes(pcState, fetchPC, inst);
518         //else
519         //    decoder->process();
520
521         //Decode an instruction if one is ready. Otherwise, we'll have to
522         //fetch beyond the MachInst at the current pc.
523         instPtr = decoder->decode(pcState);
524         if (instPtr) {
525             t_info.stayAtPC = false;
526             thread->pcState(pcState);
527         } else {
528             t_info.stayAtPC = true;
529             t_info.fetchOffset += sizeof(MachInst);
530         }
531
532         //If we decoded an instruction and it's microcoded, start pulling
533         //out micro ops
534         if (instPtr && instPtr->isMacroop()) {
535             curMacroStaticInst = instPtr;
536             curStaticInst =
537                 curMacroStaticInst->fetchMicroop(pcState.microPC());
538         } else {
539             curStaticInst = instPtr;
540         }
541     } else {
542         //Read the next micro op from the macro op
543         curStaticInst = curMacroStaticInst->fetchMicroop(pcState.microPC());
544     }
545
546     //If we decoded an instruction this "tick", record information about it.
547     if (curStaticInst) {
548 #if TRACING_ON
549         traceData = tracer->getInstRecord(curTick(), thread->getTC(),
550                 curStaticInst, thread->pcState(), curMacroStaticInst);
551
552         DPRINTF(Decode,"Decode: Decoded %s instruction: %#x\n",
553                 curStaticInst->getName(), curStaticInst->machInst);
554 #endif // TRACING_ON
555     }
556
557     if (branchPred && curStaticInst &&
558         curStaticInst->isControl()) {
559         // Use a fake sequence number since we only have one
560         // instruction in flight at the same time.
561         const InstSeqNum cur_sn(0);
562         t_info.predPC = thread->pcState();
563         const bool predict_taken(
564             branchPred->predict(curStaticInst, cur_sn, t_info.predPC,
565                                 curThread));
566
567         if (predict_taken)
568             ++t_info.numPredictedBranches;
569     }
570 }
```

###execute

###preExecute: decode instruction and predict branch



###Instruction execution: execute decoded microop instruction
For memory operation (line 798-819),
it invokes *initiateAcc* method of current microop 
represented by the curStaticInst (line 800).
As we have seen before,
for each load/store microop, it defines initiateAcc function,
for example, for Ld, it defines Ld::initiateAcc.

Otherwise, for non-memory instruction,
it invokes *execute* method of microop 
instead of initiateAcc.



###postExecute: manage statistics related with execution

###adnvanceInst: start to fetch next instruction

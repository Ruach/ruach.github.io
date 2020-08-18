---
layout: post
titile: "Microops in GEM5"
categories: GEM5, Microops
---
As we've seen in the macroop to microop parsing,
each microop invocation in macrocode definition
can be interpreted python class
associated with that microop.
From the retrieved python microop,
it can further retrieve automatically generated CPP class
that are actually instantiated by 
CPP macroop class.

In this posting, we will take a look at ld microop as example.
First of all,
let's start from the python microop class associated with ld.
Because there are multiple microops 
that need to access memory for load opeartion,
*defineMicroLoadOp* function provides a general way 
to define load related microops.

*gem5/src/arch/x86/isa/microops/ldstop.isa*
```python
{% raw %}
417 let {{
418
419     # Make these empty strings so that concatenating onto
420     # them will always work.
421     header_output = ""
422     decoder_output = ""
423     exec_output = ""
424
425     segmentEAExpr = \
426         'bits(scale * Index + Base + disp, addressSize * 8 - 1, 0);'
427
428     calculateEA = 'EA = SegBase + ' + segmentEAExpr
429
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
481
482     defineMicroLoadOp('Ld', 'Data = merge(Data, Mem, dataSize);',
483                             'Data = Mem & mask(dataSize * 8);')
{% endraw %}
```

###python microop class generation
Note that Ld microop is also defined through the defineMicroLoadOp (line 482).
Then how the defineMicroLoadOp generates load related microops?
As we've seen in the previous posting,
each microop can be represned by corresponding python class.
Line 468-480 defines LoadOp class
bounded to one microop.
Note that each LoadOP class of different microop 
will contain different className and mnemonic (line 477-478).

And the generated python class is 
stored in the *microopClasses* dictionary.
Remeber that this microopClasses dictionary is used 
by the MicroAssembler to parse macroops 
because it consists of various microops.

###cpp microop class generation
Not only the python microop class,
but also the cpp microop class is defined by the defineMicroLoadOp function.
Compared to python microop class,
CPP microop class is automatically generated 
by using a template and proper substitution.

Although the same templates are used 
to retrieve different microop classes in cpp format,
it needs some data structure describing
semantic of different microop
that actually generates difference in the automatically generated cpp class. 

For that data structure describing one specific microop,
It makes use of InstObjParams class 
that requires microop mnemonic, 
code defining the microop, 
and arguments of it.
When we look at the lines 441-449,
it generates InstObjParams instance 
by making use of defineMicroLoadOp's operands.

Note that each invocation of defineMicroLoadOp 
should have different operands,
and it results in different InstObjParams creation.
Also this different InstObjParams result in 
different microop class generation in CPP.

After generating iop list,
code at line 450-455
automatically generates CPP code.
The template method called with the iop
substitutes some string part of the template
and defines class definition and header of microop 
in CPP format.
 
###InstObjParams
*gem5/src/arch/isa_parser.py*
```python
1413 class InstObjParams(object):
1414     def __init__(self, parser, mnem, class_name, base_class = '',
1415                  snippets = {}, opt_args = []):
1416         self.mnemonic = mnem
1417         self.class_name = class_name
1418         self.base_class = base_class
1419         if not isinstance(snippets, dict):
1420             snippets = {'code' : snippets}
1421         compositeCode = ' '.join(map(str, snippets.values()))
1422         self.snippets = snippets
1423
1424         self.operands = OperandList(parser, compositeCode)
1425
1426         # The header of the constructor declares the variables to be used
1427         # in the body of the constructor.
1428         header = ''
1429         header += '\n\t_numSrcRegs = 0;'
1430         header += '\n\t_numDestRegs = 0;'
1431         header += '\n\t_numFPDestRegs = 0;'
1432         header += '\n\t_numVecDestRegs = 0;'
1433         header += '\n\t_numVecElemDestRegs = 0;'
1434         header += '\n\t_numVecPredDestRegs = 0;'
1435         header += '\n\t_numIntDestRegs = 0;'
1436         header += '\n\t_numCCDestRegs = 0;'
1437
1438         self.constructor = header + \
1439                            self.operands.concatAttrStrings('constructor')
1440
1441         self.flags = self.operands.concatAttrLists('flags')
1442
1443         self.op_class = None
1444
1445         # Optional arguments are assumed to be either StaticInst flags
1446         # or an OpClass value.  To avoid having to import a complete
1447         # list of these values to match against, we do it ad-hoc
1448         # with regexps.
1449         for oa in opt_args:
1450             if instFlagRE.match(oa):
1451                 self.flags.append(oa)
1452             elif opClassRE.match(oa):
1453                 self.op_class = oa
1454             else:
1455                 error('InstObjParams: optional arg "%s" not recognized '
1456                       'as StaticInst::Flag or OpClass.' % oa)
1457
1458         # Make a basic guess on the operand class if not set.
1459         # These are good enough for most cases.
1460         if not self.op_class:
1461             if 'IsStore' in self.flags:
1462                 # The order matters here: 'IsFloating' and 'IsInteger' are
1463                 # usually set in FP instructions because of the base
1464                 # register
1465                 if 'IsFloating' in self.flags:
1466                     self.op_class = 'FloatMemWriteOp'
1467                 else:
1468                     self.op_class = 'MemWriteOp'
1469             elif 'IsLoad' in self.flags or 'IsPrefetch' in self.flags:
1470                 # The order matters here: 'IsFloating' and 'IsInteger' are
1471                 # usually set in FP instructions because of the base
1472                 # register
1473                 if 'IsFloating' in self.flags:
1474                     self.op_class = 'FloatMemReadOp'
1475                 else:
1476                     self.op_class = 'MemReadOp'
1477             elif 'IsFloating' in self.flags:
1478                 self.op_class = 'FloatAddOp'
1479             elif 'IsVector' in self.flags:
1480                 self.op_class = 'SimdAddOp'
1481             else:
1482                 self.op_class = 'IntAluOp'
1483
1484         # add flag initialization to contructor here to include
1485         # any flags added via opt_args
1486         self.constructor += makeFlagConstructor(self.flags)
1487
1488         # if 'IsFloating' is set, add call to the FP enable check
1489         # function (which should be provided by isa_desc via a declare)
1490         # if 'IsVector' is set, add call to the Vector enable check
1491         # function (which should be provided by isa_desc via a declare)
1492         if 'IsFloating' in self.flags:
1493             self.fp_enable_check = 'fault = checkFpEnableFault(xc);'
1494         elif 'IsVector' in self.flags:
1495             self.fp_enable_check = 'fault = checkVecEnableFault(xc);'
1496         else:
1497             self.fp_enable_check = ''
```

##Microop class declaration
```python
222 def template MicroLdStOpDeclare {{
223     class %(class_name)s : public %(base_class)s
224     {
225       public:
226         %(class_name)s(ExtMachInst _machInst,
227                 const char * instMnem, uint64_t setFlags,
228                 uint8_t _scale, InstRegIndex _index, InstRegIndex _base,
229                 uint64_t _disp, InstRegIndex _segment,
230                 InstRegIndex _data,
231                 uint8_t _dataSize, uint8_t _addressSize,
232                 Request::FlagsType _memFlags);
233
234         Fault execute(ExecContext *, Trace::InstRecord *) const;
235         Fault initiateAcc(ExecContext *, Trace::InstRecord *) const;
236         Fault completeAcc(PacketPtr, ExecContext *, Trace::InstRecord *) const;
237     };
238 }};

*decoder-ns.hh.inc*
```cpp
3585     class Ld : public X86ISA::LdStOp
3586     {
3587       public:
3588         Ld(ExtMachInst _machInst,
3589                 const char * instMnem, uint64_t setFlags,
3590                 uint8_t _scale, InstRegIndex _index, InstRegIndex _base,
3591                 uint64_t _disp, InstRegIndex _segment,
3592                 InstRegIndex _data,
3593                 uint8_t _dataSize, uint8_t _addressSize,
3594                 Request::FlagsType _memFlags);
3595
3596         Fault execute(ExecContext *, Trace::InstRecord *) const;
3597         Fault initiateAcc(ExecContext *, Trace::InstRecord *) const;
3598         Fault completeAcc(PacketPtr, ExecContext *, Trace::InstRecord *) const;
3599     };
```

##Microop class constructor generation
260 def template MicroLdStOpConstructor {{
261     %(class_name)s::%(class_name)s(
262             ExtMachInst machInst, const char * instMnem, uint64_t setFlags,
263             uint8_t _scale, InstRegIndex _index, InstRegIndex _base,
264             uint64_t _disp, InstRegIndex _segment,
265             InstRegIndex _data,
266             uint8_t _dataSize, uint8_t _addressSize,
267             Request::FlagsType _memFlags) :
268         %(base_class)s(machInst, "%(mnemonic)s", instMnem, setFlags,
269                 _scale, _index, _base,
270                 _disp, _segment, _data,
271                 _dataSize, _addressSize, _memFlags, %(op_class)s)
272     {
273         %(constructor)s;
274     }
275 }};

*decoder-ns.cc.inc*
```cpp
10488     Ld::Ld(
10489             ExtMachInst machInst, const char * instMnem, uint64_t setFlags,
10490             uint8_t _scale, InstRegIndex _index, InstRegIndex _base,
10491             uint64_t _disp, InstRegIndex _segment,
10492             InstRegIndex _data,
10493             uint8_t _dataSize, uint8_t _addressSize,
10494             Request::FlagsType _memFlags) :
10495         X86ISA::LdStOp(machInst, "ld", instMnem, setFlags,
10496                 _scale, _index, _base,
10497                 _disp, _segment, _data,
10498                 _dataSize, _addressSize, _memFlags, MemReadOp)
10499     {
10500
10501         _numSrcRegs = 0;
10502         _numDestRegs = 0;
10503         _numFPDestRegs = 0;
10504         _numVecDestRegs = 0;
10505         _numVecElemDestRegs = 0;
10506         _numVecPredDestRegs = 0;
10507         _numIntDestRegs = 0;
10508         _numCCDestRegs = 0;
10509         _srcRegIdx[_numSrcRegs++] = RegId(IntRegClass, INTREG_FOLDED(index, foldABit));
10510         _srcRegIdx[_numSrcRegs++] = RegId(IntRegClass, INTREG_FOLDED(base, foldABit));
10511         _srcRegIdx[_numSrcRegs++] = RegId(IntRegClass, INTREG_FOLDED(data, foldOBit));
10512         _destRegIdx[_numDestRegs++] = RegId(IntRegClass, INTREG_FOLDED(data, foldOBit));
10513         _numIntDestRegs++;
10514         _srcRegIdx[_numSrcRegs++] = RegId(MiscRegClass, MISCREG_SEG_EFF_BASE(segment));
10515         flags[IsInteger] = true;
10516         flags[IsLoad] = true;
10517         flags[IsMemRef] = true;;
10518     }
```



##Method generation required for basic load operation
### execute: modify ExecContext based on instruction
```python
 90 def template MicroLoadExecute {{
 91     Fault %(class_name)s::execute(ExecContext *xc,
 92           Trace::InstRecord *traceData) const
 93     {
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
Currently, we have a automatically generated class definition and its constructor.
However, it cannot make any change to the micro architecture state,
which means we need a method that defines semantic of a microop.
One of the important method is execute that actually change the architecture state
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
```
As mentioned in the comment,
*ExecContext* class is an abstract base class
used to manipulate state of the CPU model. 
Therefore, each CPU model provides concrete interface 
that can actually updates CPU context.

As an example, let's take a loot at simeple cpu model.

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
However, because it is an interface class,
actual memory read operation is done by the CPU class.
However, for timing CPU, 
it doesn't make use of execute,
but other autogenerated method to executed ld microop.

###InitiateAcc: send memory reference
```python
119 def template MicroLoadInitiateAcc {{
120     Fault %(class_name)s::initiateAcc(ExecContext * xc,
121             Trace::InstRecord * traceData) const
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



###completeAcc: execute memory instruction and bring the data
```python
138 def template MicroLoadCompleteAcc {{
139     Fault %(class_name)s::completeAcc(PacketPtr pkt, ExecContext * xc,
140                                       Trace::InstRecord * traceData) const
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

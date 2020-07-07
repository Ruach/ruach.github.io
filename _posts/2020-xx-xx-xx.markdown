---
layout: post
titile: "Microops in GEM5"
categories: GEM5, Microops
---
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


```cpp
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

\xxx it actually read memory by making use of physical address?


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
For memory operation, initiateAcc is the most important function
that actually initiate memory access. 
initiateAcc invokes initiateMemRead function, and
each CPU class overrides initiateMemRead method.

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
Otherwise, it invokes translateTiming function defined in data tlb object(dtb).


###completeAcc:execute memory instruction
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

Then who makes use of those automatically generated functions of microop?
Each CPU model makes use of the generated methods differently,
so we are going to look at simple/timing cpu model
which is simple one cycle cpu.

Because simple cpu model is one cycle CPU model,
it doesn't implement multiple pipeline stages.
Although it has no pipeline stages,
entire execution process can be represented as 
three separate functions: fetch and advanceInst.

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
When we look at the fetch function of the simple cpu,
we can easily find that it invokes completeIfetch function
when the next instruction is ready to be executed,
which means next instruction has been fetched from the memory.
completeIfetch instruction consists of four parts:
preExecute, instruction execution, postExecute, and advanceInst.

###preExecute: decode instruction and predict branch



###Instruction execution: execute decoded microop instruction
For memory operation (line 798-819),
it invokes initiateAcc method of current microop 
represented by the curStaticInst.
As we have seen before,
for each load/store microop, it defines initiateAcc function,
for example, for Ld, it defines Ld::initiateAcc.

Otherwise, for non-memory instruction,
it invokes execute method of microop instead of initiateAcc.






###postExecute: manage statistics related with execution

###adnvanceInst: start to fetch next instruction

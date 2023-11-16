---
layout: post
titile: "GEM5 micro-load operation to actual memory access"
categories: GEM5, Microops
---

In my previous post, I discussed the automatic generation of C++ classes for 
macroops and microops using various GEM5 tools, including a Python-based parser 
and string-based template substitution. I also provided an example, explaining 
how a class definition and its constructor for micro-load instructions are 
generated. Additionally, I presented several definitions that implement the 
actual semantics of micro-load operations, including the execute function.

The instructions are designed to change internal state of the system. More 
specifically, by executing certain instructions, they can induce specific 
changes in registers, memory, or internal states that are represented as 
architectural elements.
Given that GEM5 operates as an architecture-level emulator, the execution of a 
single micro-op should result in the alteration of a particular data structure 
representing a segment of the architecture. To achieve this, GEM5 provides the
"ExecContext" class, which emulates the entire underlying architecture. 
Additionally, the "execute" method and other definitions of the micro-operations
are designed to modify the "ExecContext" as a consequence of their execution. 
In essence, these definitions emulate the semantics of the instructions.
We will explore how the execution of a micro-op can modify the underlying 
architectural state through updating "ExecContext. To comprehend how GEM5 
executes micro-operations, we will briefly examine the pipeline of a simple 
processor.

## CPU pipeline of the simple processor: fetch-decode-execute
To understand how GEM5 emulates the entire architecture, one crucial question to
address is: **When and how does GEM5 execute the next instruction?** In other 
words, we must understand who utilizes the automatically generated micro-op 
class and its functions.
Each CPU model features a distinct pipeline architecture, and this difference 
significantly influences the execution of instructions within the pipeline. To 
shed light on this, we will examine the TimingSimple CPU model, which is the 
most basic CPU pipeline model supported by GEM5.

Here are the key characteristics of the SimpleTiming processor model in GEM5:

- **Single-Cycle Execution**: It operates on a single-cycle execution model, 
- where each instruction is executed in one clock cycle.

- **Minimal Microarchitecture**: It lacks the complexity of multiple pipeline 
- stages, making it relatively simple and easy to understand.

- **Idealized Timing**: The SimpleTiming model does not account for detailed 
- timing, such as pipeline hazards or stalls, and assumes that instructions 
- progress through the pipeline without delays.


### Processor invokes fetch at every clock tick 
To understand how the TimingSimple processor process the events,
we should understand which function will be invoked at the schedule event. 
Scheduling a specific event requires a EventFunctionWrapper instance
which contains information about event handler function.


*gem5/src/cpu/simple/timing.hh*
```cpp
 51 class TimingSimpleCPU : public BaseSimpleCPU
 52 {
......
325   private:
326 
327     EventFunctionWrapper fetchEvent;
```

As shown in the above class declaration of the TimingSimpleCPU, 
I can find that fetchEvent member field is declared as EventFunctionWrapper.
To utilize the wrapper to schedule event, 
proper initialization code is required.

*gem5/src/cpu/simple/timing.cc*
```cpp
  82 TimingSimpleCPU::TimingSimpleCPU(TimingSimpleCPUParams *p)
  83     : BaseSimpleCPU(p), fetchTranslation(this), icachePort(this),
  84       dcachePort(this), ifetch_pkt(NULL), dcache_pkt(NULL), previousCycle(0),
  85       fetchEvent([this]{ fetch(); }, name())
  86 {
  87     _status = Idle;
  88 }
```

As shown in the constructor of the TimingSimpleCPU, 
it initialize the fetchEvent member field with a function called **fetch**.
Therefore, whenever the fetchEvent is scheduled, 
the GEM5 will invoke the fetch function and start to fetch the instruction
from the memory (or cache).

### fetch: retrieving next instruction to execute from memory
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







### decode
Processor can decode the memory blocks as instruction
after the memory has been fetched from the cache or memory.
Because timing simple CPU assume memory access takes more than single cycle,
it needs to be notified when the requested memory block has been brought to the processor.

```cpp
 874 void
 875 TimingSimpleCPU::IcachePort::ITickEvent::process()
 876 {
 877     cpu->completeIfetch(pkt);
 878 }
 879 
 880 bool
 881 TimingSimpleCPU::IcachePort::recvTimingResp(PacketPtr pkt)
 882 {
 883     DPRINTF(SimpleCPU, "Received fetch response %#x\n", pkt->getAddr());
 884     // we should only ever see one response per cycle since we only
 885     // issue a new request once this response is sunk
 886     assert(!tickEvent.scheduled());
 887     // delay processing of returned data until next CPU clock edge
 888     tickEvent.schedule(pkt, cpu->clockEdge());
 889 
 890     return true;
 891 }
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
### execute: modify ExecContext based on instruction

*gem5/build/X86/arch/x86/generated/exec-ns.cc.inc*
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


###execute

###preExecute: decode instruction and predict branch



### Instruction execution: execute decoded microop instruction
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















After finishing translation,
and when the fault has not been deteced by the finish function,
it starts to read the actual data from the memory.

```cpp
 627 void
 628 TimingSimpleCPU::finishTranslation(WholeTranslationState *state)
 629 {
 630     _status = BaseSimpleCPU::Running;
 631
 632     if (state->getFault() != NoFault) {
 633         if (state->isPrefetch()) {
 634             state->setNoFault();
 635         }
 636         delete [] state->data;
 637         state->deleteReqs();
 638         translationFault(state->getFault());
 639     } else {
 640         if (!state->isSplit) {
 641             sendData(state->mainReq, state->data, state->res,
 642                      state->mode == BaseTLB::Read);
 643         } else {
 644             sendSplitData(state->sreqLow, state->sreqHigh, state->mainReq,
 645                           state->data, state->mode == BaseTLB::Read);
 646         }
 647     }
 648
 649     delete state;
 650 }
```
As shown in line 639-649, 
when the fault has not been raised during translation,
then it sends memory access packet 
to DRAM through sendData function.

```cpp
 287 void
 288 TimingSimpleCPU::sendData(const RequestPtr &req, uint8_t *data, uint64_t *res,
 289                           bool read)
 290 {
 291     SimpleExecContext &t_info = *threadInfo[curThread];
 292     SimpleThread* thread = t_info.thread;
 293
 294     PacketPtr pkt = buildPacket(req, read);
 295     pkt->dataDynamic<uint8_t>(data);
 296
 297     if (req->getFlags().isSet(Request::NO_ACCESS)) {
 298         assert(!dcache_pkt);
 299         pkt->makeResponse();
 300         completeDataAccess(pkt);
 301     } else if (read) {
 302         handleReadPacket(pkt);
 303     } else {
 304         bool do_access = true;  // flag to suppress cache access
 305
 306         if (req->isLLSC()) {
 307             do_access = TheISA::handleLockedWrite(thread, req, dcachePort.cacheBlockMask);
 308         } else if (req->isCondSwap()) {
 309             assert(res);
 310             req->setExtraData(*res);
 311         }
 312
 313         if (do_access) {
 314             dcache_pkt = pkt;
 315             handleWritePacket();
 316             threadSnoop(pkt, curThread);
 317         } else {
 318             _status = DcacheWaitResponse;
 319             completeDataAccess(pkt);
 320         }
 321     }
 322 }
```

Currently we are looking at load instruction not the store,
we are going to assume that read flag has been set.
Therefore, it invoked handleReadPacket(pkt) function 
in line 301-302.
Note that packer pkk is created as a combination of req and read
(line 294).
As req variable contains all the required address and data size 
to access memory, it should be contained in the request packet.

```cpp
 258 bool
 259 TimingSimpleCPU::handleReadPacket(PacketPtr pkt)
 260 {
 261     SimpleExecContext &t_info = *threadInfo[curThread];
 262     SimpleThread* thread = t_info.thread;
 263
 264     const RequestPtr &req = pkt->req;
 265
 266     // We're about the issues a locked load, so tell the monitor
 267     // to start caring about this address
 268     if (pkt->isRead() && pkt->req->isLLSC()) {
 269         TheISA::handleLockedRead(thread, pkt->req);
 270     }
 271     if (req->isMmappedIpr()) {
 272         Cycles delay = TheISA::handleIprRead(thread->getTC(), pkt);
 273         new IprEvent(pkt, this, clockEdge(delay));
 274         _status = DcacheWaitResponse;
 275         dcache_pkt = NULL;
 276     } else if (!dcachePort.sendTimingReq(pkt)) {
 277         _status = DcacheRetry;
 278         dcache_pkt = pkt;
 279     } else {
 280         _status = DcacheWaitResponse;
 281         // memory system takes ownership of packet
 282         dcache_pkt = NULL;
 283     }
 284     return dcache_pkt == NULL;
 285 }
```

Because CPU is connected to memory component 
through master slave ports in GEM5,
it can initiate memory access by sending request packet 
through a *sendTimingReq* method.
Because CPU goes through the data cache 
before touching the physical memory, 
the sendTimingReq is invoked on the DcachePort.

*gem5/src/mem/port.hh*
```cpp
444 inline bool
445 MasterPort::sendTimingReq(PacketPtr pkt)
446 {
447     return TimingRequestProtocol::sendReq(_slavePort, pkt);
448 }
```
*mem/protocol/timing.cc*
```cpp
 47 /* The request protocol. */
 48 
 49 bool
 50 TimingRequestProtocol::sendReq(TimingResponseProtocol *peer, PacketPtr pkt)
 51 {
 52     assert(pkt->isRequest());
 53     return peer->recvTimingReq(pkt);
 54 }
```




### recvTimingResp

When the request has been handled by the slave (DCache),
recvTimingResp method of DcachePort will be invoked 
to handle result of memory access.

```cpp
 978 bool
 979 TimingSimpleCPU::DcachePort::recvTimingResp(PacketPtr pkt)
 980 {
 981     DPRINTF(SimpleCPU, "Received load/store response %#x\n", pkt->getAddr());
 982
 983     // The timing CPU is not really ticked, instead it relies on the
 984     // memory system (fetch and load/store) to set the pace.
 985     if (!tickEvent.scheduled()) {
 986         // Delay processing of returned data until next CPU clock edge
 987         tickEvent.schedule(pkt, cpu->clockEdge());
 988         return true;
 989     } else {
 990         // In the case of a split transaction and a cache that is
 991         // faster than a CPU we could get two responses in the
 992         // same tick, delay the second one
 993         if (!retryRespEvent.scheduled())
 994             cpu->schedule(retryRespEvent, cpu->clockEdge(Cycles(1)));
 995         return false;
 996     }
 997 }
```
It seems that it doesn't handle the received packet.
However, it schedules tickEvent  
to process the recevied packet.

```cpp
 999 void
1000 TimingSimpleCPU::DcachePort::DTickEvent::process()
1001 {
1002     cpu->completeDataAccess(pkt);
1003 }
```


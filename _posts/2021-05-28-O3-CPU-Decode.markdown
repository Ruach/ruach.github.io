# Sending fetched instructions to decode stage
*gem5/src/cpu/o3/fetch_impl.hh*
```cpp
 961 
 962     // Pick a random thread to start trying to grab instructions from
 963     auto tid_itr = activeThreads->begin();
 964     std::advance(tid_itr, random_mt.random<uint8_t>(0, activeThreads->size() - 1));
 965 
 966     while (available_insts != 0 && insts_to_decode < decodeWidth) {
 967         ThreadID tid = *tid_itr;
 968         if (!stalls[tid].decode && !fetchQueue[tid].empty()) {
 969             const auto& inst = fetchQueue[tid].front();
 970             toDecode->insts[toDecode->size++] = inst;
 971             DPRINTF(Fetch, "[tid:%i] [sn:%llu] Sending instruction to decode "
 972                     "from fetch queue. Fetch queue size: %i.\n",
 973                     tid, inst->seqNum, fetchQueue[tid].size());
 974 
 975             wroteToTimeBuffer = true;
 976             fetchQueue[tid].pop_front();
 977             insts_to_decode++;
 978             available_insts--;
 979         }
 980 
 981         tid_itr++;
 982         // Wrap around if at end of active threads list
 983         if (tid_itr == activeThreads->end())
 984             tid_itr = activeThreads->begin();
 985     }
 986 
 987     // If there was activity this cycle, inform the CPU of it.
 988     if (wroteToTimeBuffer) {
 989         DPRINTF(Activity, "Activity this cycle.\n");
 990         cpu->activityThisCycle();
 991     }
 992 
 993     // Reset the number of the instruction we've fetched.
 994     numInst = 0;
 995 }   //end of the fetch.tick
```
The last job of the fetch stage is passing the fetched instructions
to the next stage, decode stage. 
On the above code, **toDecode** member field of the fetch 
is used as an storage located in between the fetch and decode stage. 

## FetchStruct: passing fetch stage's information to decode stage
*gem5/src/cpu/o3/fetch.hh*
```cpp
431     //Might be annoying how this name is different than the queue.
432     /** Wire used to write any information heading to decode. */
433     typename TimeBuffer<FetchStruct>::wire toDecode;
```

The toDecode is declared as a wire class defined in the TimeBuffer class. 
Also, because the TimeBuffer is a template class, 
it passes the FetchStruct that contains all fetch stage's information
required by the decode stage. Let's take a look at the FetchStruct 
to understand which information is passed to the decode stage. 

*gem5/src/cpu/o3/cpu_policy.hh*
```cpp
 60 template<class Impl>
 61 struct SimpleCPUPolicy
 62 {
 ......
 89     /** The struct for communication between fetch and decode. */
 90     typedef DefaultFetchDefaultDecode<Impl> FetchStruct;
 91 
 92     /** The struct for communication between decode and rename. */
 93     typedef DefaultDecodeDefaultRename<Impl> DecodeStruct;
 94 
 95     /** The struct for communication between rename and IEW. */
 96     typedef DefaultRenameDefaultIEW<Impl> RenameStruct;
 97 
 98     /** The struct for communication between IEW and commit. */
 99     typedef DefaultIEWDefaultCommit<Impl> IEWStruct;
100 
101     /** The struct for communication within the IEW stage. */
102     typedef ::IssueStruct<Impl> IssueStruct;
103 
104     /** The struct for all backwards communication. */
105     typedef TimeBufStruct<Impl> TimeStruct;
```

*gem5/src/cpu/o3/comm.h*
```cpp
 55 /** Struct that defines the information passed from fetch to decode. */
 56 template<class Impl>
 57 struct DefaultFetchDefaultDecode {
 58     typedef typename Impl::DynInstPtr DynInstPtr;
 59 
 60     int size;
 61 
 62     DynInstPtr insts[Impl::MaxWidth];
 63     Fault fetchFault;
 64     InstSeqNum fetchFaultSN;
 65     bool clearFetchFault;
 66 };
```
As shown in the above code, 
it passes the instructions fetched from the Icache. 
Then how this information is passed to the decode stage?
The answer is the TimeBuffer!

## TimeBuffer and wire sending the data between two stages
In actual hardware implementation, the register should be placed 
in between the two pipeline stages to share the information
processed by the previous stage to the next stage. 
For that purpose, GEM5 utilize the TimeBuffer and Wire classes. 

### TimeBuffer implementation and usage 
TimeBuffer is implemented as a template class 
designed to pass any information 
between two different stages. 
Also, it emulates actual behavior of registers.
Therefore, at every clock tick, 
the TimeBuffer is advanced 
and points to different content of the registers.

### Constructor and Desctructor of the TimeBuffer
```cpp
 39 template <class T>
 40 class TimeBuffer
 41 {
 42   protected:
 43     int past;
 44     int future;
 45     unsigned size;
 46     int _id;
 47 
 48     char *data;
 49     std::vector<char *> index;
 50     unsigned base;
 51 
 52     void valid(int idx) const
 53     {
 54         assert (idx >= -past && idx <= future);
 55     }
......
139   public:
140     TimeBuffer(int p, int f)
141         : past(p), future(f), size(past + future + 1),
142           data(new char[size * sizeof(T)]), index(size), base(0)
143     {   
144         assert(past >= 0 && future >= 0);
145         char *ptr = data; 
146         for (unsigned i = 0; i < size; i++) {
147             index[i] = ptr;
148             std::memset(ptr, 0, sizeof(T));
149             new (ptr) T;
150             ptr += sizeof(T);
151         }
152         
153         _id = -1;
154     }
155 
156     TimeBuffer()
157         : data(NULL)
158     {
159     }
160 
161     ~TimeBuffer()
162     {
163         for (unsigned i = 0; i < size; ++i)
164             (reinterpret_cast<T *>(index[i]))->~T();
165         delete [] data;
166     }
```
Because the TimeBuffer needs to allocate and deallocate new class object 
at every clock cycle, 
it's constructor is designed to utilize 
a preallocated memory called **data** member field. 
With the help of **placement new**, 
its constructor can initialize 
new object at specific location, index vector. 
As shown in its constructor, 
it populates T typed object, 
size times on the data array. 
It makes the index vector point to the allocated objects. 
At its desctructor, it deletes the data array and every objects
pointed to by the index vector. 


### advance TimeBuffer
```cpp
 542     //Tick each of the stages
 543     fetch.tick();
 544 
 545     decode.tick();
 546 
 547     rename.tick();
 548 
 549     iew.tick();
 550 
 551     commit.tick();
 552 
 553     // Now advance the time buffers
 554     timeBuffer.advance();
 555 
 556     fetchQueue.advance();
 557     decodeQueue.advance();
 558     renameQueue.advance();
 559     iewQueue.advance();
 560 
 561     activityRec.advance();
```
The most important function of the TimeBuffer is the **advance**.
This function is invoked at every clock cycle of the processor 
to advance the TimeBuffer. 
Let's take a look at how the advance function 
emulates next clock tick. 

```cpp
178     void
179     advance()
180     {
181         if (++base >= size)
182             base = 0;
183 
184         int ptr = base + future;
185         if (ptr >= (int)size)
186             ptr -= size;
187         (reinterpret_cast<T *>(index[ptr]))->~T();
188         std::memset(index[ptr], 0, sizeof(T));
189         new (index[ptr]) T;
190     }
```

The base member field is initialized as zero at the construction 
and incremented at every clock cycle 
because the advance function is invoked at every clock cycle. 
Also, because it emulates circular storage, 
the base should be initialized as zero
when it exceeds size (line 181-182). 
And the **future** is the fixed constant 
passed by the configuration python script.
Therefore, after the first initialization with offset future, 
at every clock cycle, it allocates new object typed T. 
Before populating new object, 
it first invoke deconstructor (line 188) 
and initiate new object with the placement new (line 189). 



## Wire
### Example motivating interaction between fetch and decode
*gem5/src/cpu/o3/cpu.cc*
```cpp
 182     // Also setup each of the stages' queues.
 183     fetch.setFetchQueue(&fetchQueue);
 184     decode.setFetchQueue(&fetchQueue);
```

*gem5/src/cpu/o3/fetch_impl.hh*
```cpp
 312 template<class Impl>
 313 void
 314 DefaultFetch<Impl>::setFetchQueue(TimeBuffer<FetchStruct> *ftb_ptr)
 315 {
 316     // Create wire to write information to proper place in fetch time buf.
 317     toDecode = ftb_ptr->getWire(0);
 318 }
```
*gem5/src/cpu/o3/decode_impl.hh*
```cpp
195 template<class Impl>
196 void
197 DefaultDecode<Impl>::setFetchQueue(TimeBuffer<FetchStruct> *fq_ptr)
198 {
199     fetchQueue = fq_ptr;
200 
201     // Setup wire to read information from fetch queue.
202     fromFetch = fetchQueue->getWire(-fetchToDecodeDelay);
203 }
```
*gem5/src/cpu/timebuf.hh*
```cpp
234     wire getWire(int idx)
235     {
236         valid(idx);
237 
238         return wire(this, idx);
239     }
```

As shown in the above code, 
two different stages fetch and decode 
invoke setFetchQueue function 
with the same TimeBuffer, fetchQueue.
However, 
note that those two invocations are serviced 
from different functions of each class. 
As shown in the above code, 
both function invokes getWire, 
but with different argument, 
0 and -fetchToDecodeDelay respectively. 
The getWire function returns the wire object 
initialized with this and idx.
Here this means the TimeBuffer itself and this will be assigned 
to the buffer member field of the wire object. 
Also, idx will be assigned to 
the index member field of the wire object.
Because the index is a constant number and used to access the register 
managed by the buffer, it will generate fetchToDecodeDelay clock timing delays 
between the fetch and decode stage.
Let's see how this timing delay can be imposed on the register access in detail.

### Wire overloads the member reference operator to access the TimeBuffer
Remember that the wire has member field buffer which is the TimeBuffer that actually 
maintains all the register values that should be passed to the next stage. 
However, in general, the register is a flip-flop it cannot be read and written
at the same cycle. 
Therefore, naturally, the next stage will get the data written to the register 
after n clock cycles are elapsed.
This behavior of the register is emulated by the wire and TimeBuffer.

```cpp
 57   public:
 58     friend class wire;
 59     class wire
 60     {
 61         friend class TimeBuffer;
 62       protected:
 63         TimeBuffer<T> *buffer;
 64         int index;
 65 
 66         void set(int idx)
 67         {   
 68             buffer->valid(idx);
 69             index = idx;
 70         }
 71 
 72         wire(TimeBuffer<T> *buf, int i)
 73             : buffer(buf), index(i)
 74         { }
......
134         T &operator*() const { return *buffer->access(index); }
135         T *operator->() const { return buffer->access(index); }
136     };
```

When the wire is accessed by the -> operator, it invokes 
access function of the TimeBuffer contained in the buffer member field. 
Also note that it passes the index argument set at the construction of the wire. 

```cpp
192   protected:
193     //Calculate the index into this->index for element at position idx
194     //relative to now
195     inline int calculateVectorIndex(int idx) const
196     {
197         //Need more complex math here to calculate index.
198         valid(idx);
199 
200         int vector_index = idx + base;
201         if (vector_index >= (int)size) {
202             vector_index -= size;
203         } else if (vector_index < 0) {
204             vector_index += size;
205         }
206 
207         return vector_index;
208     }
209 
210   public:
211     T *access(int idx)
212     {
213         int vector_index = calculateVectorIndex(idx);
214 
215         return reinterpret_cast<T *>(index[vector_index]);
216     }
```
When the access is invoked, it first calculates the index for the vector. 
Note that it adds two variable idx and base. 
The base member field is increased by 1 every clock cycle as we've seen 
in the **advance** function before. 
the idx field is passed from the wire class that embeds the TimeBuffer. 
For example, it is 0 and -1 for the fetch and decode stage respectively. 
Therefore, in this settings, the decode stage will access the register 
set by the previous clock cycle by the fetch stage. 
Therefore, by setting the index field of the wire at its initialization properly, 
we can set the delays of register access in two different stages. 


# Decode stage pipeline analysis 

*gem5/src/cpu/o3/decode_impl.hh*
## tick of the decode stage
```cpp
567 template<class Impl>
568 void
569 DefaultDecode<Impl>::tick()
570 {
571     wroteToTimeBuffer = false;
572 
573     bool status_change = false;
574 
575     toRenameIndex = 0;
576 
577     list<ThreadID>::iterator threads = activeThreads->begin();
578     list<ThreadID>::iterator end = activeThreads->end();
579 
580     sortInsts();
581 
582     //Check stall and squash signals.
583     while (threads != end) {
584         ThreadID tid = *threads++;
585 
586         DPRINTF(Decode,"Processing [tid:%i]\n",tid);
587         status_change =  checkSignalsAndUpdate(tid) || status_change;
588 
589         decode(status_change, tid);
590     }
591 
592     if (status_change) {
593         updateStatus();
594     }
595 
596     if (wroteToTimeBuffer) {
597         DPRINTF(Activity, "Activity this cycle.\n");
598 
599         cpu->activityThisCycle();
600     }
601 }
```
As we've seen before, the tick function of each stage is the most important function
because it is executed every core clock cycle. 
The tick function consists of three important functions: sortInsts, checkSignalsAndUpdate and decode

## sortInsts
At the end of the decode stage, it pushes the fetched instructions to the 
toDecode register buffers. Therefore, the decode stage should fetch those instructions
from the same register located in between the fetch and decode stage. 
```cpp
483 template <class Impl>
484 void
485 DefaultDecode<Impl>::sortInsts()
486 {
487     int insts_from_fetch = fromFetch->size;
488     for (int i = 0; i < insts_from_fetch; ++i) {
489         insts[fromFetch->insts[i]->threadNumber].push(fromFetch->insts[i]);
490     }
491 }   
```

The sortInsts extracts the instructions 
stored in the register (**fromFetch**) and 
save them in the local instruction buffer (**insts**). 
Note that the register changes every tick, 
so each stage should copy and paste the register data
to its local memory to process. 

## checkSignalsAndUpdate
```cpp
507 template <class Impl>
508 bool
509 DefaultDecode<Impl>::checkSignalsAndUpdate(ThreadID tid)
510 {
511     // Check if there's a squash signal, squash if there is.
512     // Check stall signals, block if necessary.
513     // If status was blocked
514     //     Check if stall conditions have passed
515     //         if so then go to unblocking
516     // If status was Squashing
517     //     check if squashing is not high.  Switch to running this cycle.
518
519     // Update the per thread stall statuses.
520     readStallSignals(tid);
521
522     // Check squash signals from commit.
523     if (fromCommit->commitInfo[tid].squash) {
524
525         DPRINTF(Decode, "[tid:%i] Squashing instructions due to squash "
526                 "from commit.\n", tid);
527
528         squash(tid);
529
530         return true;
531     }
532
533     if (checkStall(tid)) {
534         return block(tid);
535     }
```
Before executing the decode function, 
it should first check 
whether the other stages has sent a signal to stall. 

### readStallSignals 
```cpp
493 template<class Impl>
494 void
495 DefaultDecode<Impl>::readStallSignals(ThreadID tid)
496 {
497     if (fromRename->renameBlock[tid]) {
498         stalls[tid].rename = true;
499     }
500 
501     if (fromRename->renameUnblock[tid]) {
502         assert(stalls[tid].rename);
503         stalls[tid].rename = false;
504     }
505 }
```
Rename stage can send two signals to the decode stage, 
block signal and unblock signal through the fromRename wire.
Based on the signal sent from the rename stage, 
it sets or unset an associated entry of the member field stalls. 

### When stall, just block the decode and return
```cpp
234 template<class Impl>
235 bool
236 DefaultDecode<Impl>::checkStall(ThreadID tid) const
237 {
238     bool ret_val = false;
239 
240     if (stalls[tid].rename) {
241         DPRINTF(Decode,"[tid:%i] Stall fom Rename stage detected.\n", tid);
242         ret_val = true;
243     }
244 
245     return ret_val;
246 }
```

When the decode stage has received the stall signal, 
it returns true, 
which results in invoking block function and 
returning is result. 

```cpp
255 template<class Impl>
256 bool
257 DefaultDecode<Impl>::block(ThreadID tid)
258 {
259     DPRINTF(Decode, "[tid:%i] Blocking.\n", tid);
260 
261     // Add the current inputs to the skid buffer so they can be
262     // reprocessed when this stage unblocks.
263     skidInsert(tid);
264 
265     // If the decode status is blocked or unblocking then decode has not yet
266     // signalled fetch to unblock. In that case, there is no need to tell
267     // fetch to block.
268     if (decodeStatus[tid] != Blocked) {
269         // Set the status to Blocked.
270         decodeStatus[tid] = Blocked;
271 
272         if (toFetch->decodeUnblock[tid]) {
273             toFetch->decodeUnblock[tid] = false;
274         } else {
275             toFetch->decodeBlock[tid] = true;
276             wroteToTimeBuffer = true;
277         }
278 
279         return true;
280     }
281 
282     return false;
283 }
```

When the decode stage has instruction to be processed
delivered from the fetch stage,
it needs to be maintained in the skid buffer 
so that they can be reprocessed 
when the decode stage is unblocked.
Note that different pipelines can still works 
even though the decode pipeline is blocked,
and the input can continuously arrive to the decode stage. 


### squash pipeline when the commit stage sent squash signal  
After reading the stall signal, it should also check 
whether the commit stage has sent a squash signal.
The decode stage can check whether it needs to squash 
by checking the fromCommit wire. 

```cpp
304 template<class Impl>
305 void
306 DefaultDecode<Impl>::squash(const DynInstPtr &inst, ThreadID tid)
307 {
308     DPRINTF(Decode, "[tid:%i] [sn:%llu] Squashing due to incorrect branch "
309             "prediction detected at decode.\n", tid, inst->seqNum);
310
311     // Send back mispredict information.
312     toFetch->decodeInfo[tid].branchMispredict = true;
313     toFetch->decodeInfo[tid].predIncorrect = true;
314     toFetch->decodeInfo[tid].mispredictInst = inst;
315     toFetch->decodeInfo[tid].squash = true;
316     toFetch->decodeInfo[tid].doneSeqNum = inst->seqNum;
317     toFetch->decodeInfo[tid].nextPC = inst->branchTarget();
318     toFetch->decodeInfo[tid].branchTaken = inst->pcState().branching();
319     toFetch->decodeInfo[tid].squashInst = inst;
320     if (toFetch->decodeInfo[tid].mispredictInst->isUncondCtrl()) {
321             toFetch->decodeInfo[tid].branchTaken = true;
322     }
323
324     InstSeqNum squash_seq_num = inst->seqNum;
325
326     // Might have to tell fetch to unblock.
327     if (decodeStatus[tid] == Blocked ||
328         decodeStatus[tid] == Unblocking) {
329         toFetch->decodeUnblock[tid] = 1;
330     }
331
332     // Set status to squashing.
333     decodeStatus[tid] = Squashing;
334
335     for (int i=0; i<fromFetch->size; i++) {
336         if (fromFetch->insts[i]->threadNumber == tid &&
337             fromFetch->insts[i]->seqNum > squash_seq_num) {
338             fromFetch->insts[i]->setSquashed();
339         }
340     }
341
342     // Clear the instruction list and skid buffer in case they have any
343     // insts in them.
344     while (!insts[tid].empty()) {
345         insts[tid].pop();
346     }
347
348     while (!skidBuffer[tid].empty()) {
349         skidBuffer[tid].pop();
350     }
351
352     // Squash instructions up until this one
353     cpu->removeInstsUntil(squash_seq_num, tid);
354 }
```

Note that squash signal incurs complex operations compared to stalls.
When the stall signal is received, 
the decode stage just waits until 
the stall signal is removed, receiving the unblock signal. 
However, when the stall signal is received, 
it should clear out the pipeline and associated data structures. 


### When the decode stage finishes blocking and squashing operation
```cpp
508 bool
509 DefaultDecode<Impl>::checkSignalsAndUpdate(ThreadID tid)
510 {
......
537     if (decodeStatus[tid] == Blocked) {
538         DPRINTF(Decode, "[tid:%i] Done blocking, switching to unblocking.\n",
539                 tid);
540
541         decodeStatus[tid] = Unblocking;
542
543         unblock(tid);
544
545         return true;
546     }
547
548     if (decodeStatus[tid] == Squashing) {
549         // Switch status to running if decode isn't being told to block or
550         // squash this cycle.
551         DPRINTF(Decode, "[tid:%i] Done squashing, switching to running.\n",
552                 tid);
553
554         decodeStatus[tid] = Running;
555
556         return false;
557     }
558
559     // If we've reached this point, we have not gotten any signals that
560     // cause decode to change its status.  Decode remains the same as before.
561     return false;
562 }
```

After the decode stage is recovered from the stall or squashing. 
it needs to change the block or stall state 
to the Running state so that it can
receive the instructions to decode from the fetch stage. 
For the Blocked state, 
it will execute the line 537-546 
And when the squash signal is turned off from commit stage, 
it will execute the rest of the code (548-557). 

## Why we need another decode even though we decoded?
It would be confusing 
because we already finished instruction decoding 
in the fetch stage. 
We already know which instructions are located 
in the fetch buffer. 
Why we need another decode function?
The decode stage does not do much, but 
it should check any PC-relative branches are correct.
Most of the decode operations are actually done 
by the decodeInsts function.

600 template<class Impl>
601 void
602 DefaultDecode<Impl>::decode(bool &status_change, ThreadID tid)
603 {
604     // If status is Running or idle,
605     //     call decodeInsts()
606     // If status is Unblocking,
607     //     buffer any instructions coming from fetch
608     //     continue trying to empty skid buffer
609     //     check if stall conditions have passed
610 
611     if (decodeStatus[tid] == Blocked) {
612         ++decodeBlockedCycles;
613     } else if (decodeStatus[tid] == Squashing) {
614         ++decodeSquashCycles;
615     }
616 
617     // Decode should try to decode as many instructions as its bandwidth
618     // will allow, as long as it is not currently blocked.
619     if (decodeStatus[tid] == Running ||
620         decodeStatus[tid] == Idle) {
621         DPRINTF(Decode, "[tid:%i] Not blocked, so attempting to run "
622                 "stage.\n",tid);
623 
624         decodeInsts(tid);
625     } else if (decodeStatus[tid] == Unblocking) {
626         // Make sure that the skid buffer has something in it if the
627         // status is unblocking.
628         assert(!skidsEmpty());
629 
630         // If the status was unblocking, then instructions from the skid
631         // buffer were used.  Remove those instructions and handle
632         // the rest of unblocking.
633         decodeInsts(tid);
634 
635         if (fetchInstsValid()) {
636             // Add the current inputs to the skid buffer so they can be
637             // reprocessed when this stage unblocks.
638             skidInsert(tid);
639         }
640 
641         status_change = unblock(tid) || status_change;
642     }
643 }

### decode stage check buffers to retrieve instruction to decode
```cpp
645 template <class Impl>
646 void
647 DefaultDecode<Impl>::decodeInsts(ThreadID tid)
648 {
649     // Instructions can come either from the skid buffer or the list of
650     // instructions coming from fetch, depending on decode's status.
651     int insts_available = decodeStatus[tid] == Unblocking ?
652         skidBuffer[tid].size() : insts[tid].size();
653 
654     if (insts_available == 0) {
655         DPRINTF(Decode, "[tid:%i] Nothing to do, breaking out"
656                 " early.\n",tid);
657         // Should I change the status to idle?
658         ++decodeIdleCycles;
659         return;
660     } else if (decodeStatus[tid] == Unblocking) {
661         DPRINTF(Decode, "[tid:%i] Unblocking, removing insts from skid "
662                 "buffer.\n",tid);
663         ++decodeUnblockCycles;
664     } else if (decodeStatus[tid] == Running) {
665         ++decodeRunCycles;
666     }
667 
668     std::queue<DynInstPtr>
669         &insts_to_decode = decodeStatus[tid] == Unblocking ?
670         skidBuffer[tid] : insts[tid];
671 
672     DPRINTF(Decode, "[tid:%i] Sending instruction to rename.\n",tid);
```

Note that the decodeInsts can be invoked
in two different state of the decode stage. 
The Running and Unblocking. 
Running status means that decode stage 
continuously receive the packet from the fetch stage.
However, the Unblocking stage means that 
it was blocked and was recovering,
which means the packets are still in the skidBuffer.
Therefore, 
it should decode instructions
stacked in the skidBuffer
while it has been blocked.


### forwarding decoded instructions to rename stage
```cpp
185 template<class Impl>
186 void
187 DefaultDecode<Impl>::setDecodeQueue(TimeBuffer<DecodeStruct> *dq_ptr)
188 {
189     decodeQueue = dq_ptr;
190 
191     // Setup wire to write information to proper place in decode queue.
192     toRename = decodeQueue->getWire(0);
193 }
```

Similar to the toDecode wire in the fetch stage, 
decode stage needs a wire 
to send the decoded instructions to another register 
connected with the rename stage. 
For that purpose, it declares toRename wire. 

```cpp
674     while (insts_available > 0 && toRenameIndex < decodeWidth) {
675         assert(!insts_to_decode.empty());
676 
677         DynInstPtr inst = std::move(insts_to_decode.front());
678 
679         insts_to_decode.pop();
680 
681         DPRINTF(Decode, "[tid:%i] Processing instruction [sn:%lli] with "
682                 "PC %s\n", tid, inst->seqNum, inst->pcState());
683 
684         if (inst->isSquashed()) {
685             DPRINTF(Decode, "[tid:%i] Instruction %i with PC %s is "
686                     "squashed, skipping.\n",
687                     tid, inst->seqNum, inst->pcState());
688             
689             ++decodeSquashedInsts;
690             
691             --insts_available;
692             
693             continue;
694         }
695 
696         // Also check if instructions have no source registers.  Mark
697         // them as ready to issue at any time.  Not sure if this check
698         // should exist here or at a later stage; however it doesn't matter
699         // too much for function correctness.
700         if (inst->numSrcRegs() == 0) {
701             inst->setCanIssue();
702         }
703 
704         // This current instruction is valid, so add it into the decode
705         // queue.  The next instruction may not be valid, so check to
706         // see if branches were predicted correctly.
707         toRename->insts[toRenameIndex] = inst;
708 
709         ++(toRename->size);
710         ++toRenameIndex;
711         ++decodeDecodedInsts;
712         --insts_available;
```

The while loop selects one instruction from the buffer 
and sends it to the rename stage
through the toRename wire. 

```cpp
720         // Ensure that if it was predicted as a branch, it really is a
721         // branch.
722         if (inst->readPredTaken() && !inst->isControl()) {
723             panic("Instruction predicted as a branch!");
724 
725             ++decodeControlMispred;
726 
727             // Might want to set some sort of boolean and just do
728             // a check at the end
729             squash(inst, inst->threadNumber);
730 
731             break;
732         }
733 
734         // Go ahead and compute any PC-relative branches.
735         // This includes direct unconditional control and
736         // direct conditional control that is predicted taken.
737         if (inst->isDirectCtrl() &&
738            (inst->isUncondCtrl() || inst->readPredTaken()))
739         {
740             ++decodeBranchResolved;
741 
742             if (!(inst->branchTarget() == inst->readPredTarg())) {
743                 ++decodeBranchMispred;
744 
745                 // Might want to set some sort of boolean and just do
746                 // a check at the end
747                 squash(inst, inst->threadNumber);
748                 TheISA::PCState target = inst->branchTarget();
749 
750                 DPRINTF(Decode,
751                         "[tid:%i] [sn:%llu] "
752                         "Updating predictions: PredPC: %s\n",
753                         tid, inst->seqNum, target);
754                 //The micro pc after an instruction level branch should be 0
755                 inst->setPredTarg(target);
756                 break;
757             }
758         }
759     } //end of the while loop
```

One thing to note is 
it really decodes the instruction and check 
whether the current instruction is really branch.
If it was predicted as a branch,
but turned out to be a non-branch instruction,
then it should squash the current instruction. 



```cpp
761     // If we didn't process all instructions, then we will need to block
762     // and put all those instructions into the skid buffer.
763     if (!insts_to_decode.empty()) {
764         block(tid);
765     }
766 
767     // Record that decode has written to the time buffer for activity
768     // tracking.
769     if (toRenameIndex) {
770         wroteToTimeBuffer = true;
771     }

```




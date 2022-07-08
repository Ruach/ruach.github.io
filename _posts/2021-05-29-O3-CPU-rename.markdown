# Rename 
It maintains the rename history of all instructions 
with destination registers, storing the arch register, 
the new physical register, and the old physical register.
The information is required 
to enable undoing of mappings 
if squashing happens, or
freeing up registers upon commit. 
Rename stage can be blocked
when the ROB, IQ, or LSQ is going to be full. 
Rename also handles 
barriers and serializing instructions
by stalling them in rename until the back-end drains.
It blocks the stage until the ROB is empty,
and there are no instructions in flight to the ROB.

### Interface of rename stage
**cpu/o3/rename_impl.hh**
```cpp
 214 template <class Impl>
 215 void
 216 DefaultRename<Impl>::setTimeBuffer(TimeBuffer<TimeStruct> *tb_ptr)
 217 {
 218     timeBuffer = tb_ptr;
 219 
 220     // Setup wire to read information from time buffer, from IEW stage.
 221     fromIEW = timeBuffer->getWire(-iewToRenameDelay);
 222 
 223     // Setup wire to read infromation from time buffer, from commit stage.
 224     fromCommit = timeBuffer->getWire(-commitToRenameDelay);
 225 
 226     // Setup wire to write information to previous stages.
 227     toDecode = timeBuffer->getWire(0);
 228 }
 229 
 230 template <class Impl>
 231 void
 232 DefaultRename<Impl>::setRenameQueue(TimeBuffer<RenameStruct> *rq_ptr)
 233 {
 234     renameQueue = rq_ptr;
 235 
 236     // Setup wire to write information to future stages.
 237     toIEW = renameQueue->getWire(0);
 238 }
 239 
 240 template <class Impl>
 241 void
 242 DefaultRename<Impl>::setDecodeQueue(TimeBuffer<DecodeStruct> *dq_ptr)
 243 {
 244     decodeQueue = dq_ptr;
 245 
 246     // Setup wire to get information from decode.
 247     fromDecode = decodeQueue->getWire(-decodeToRenameDelay);
 248 }
```
Mainly, there are three interfaces connected to the rename stage.
First of all, 
to deliver the information processed by the rename stage
to the IEW stage, it has toIEW wire. 
Also, to read some information from two other stages, decode and commit,
it sets up fromDecode and fromCommit wires. 


## Tick function of the rename stage
```cpp
 427 template <class Impl>
 428 void
 429 DefaultRename<Impl>::tick()
 430 {
 431     wroteToTimeBuffer = false;
 432 
 433     blockThisCycle = false;
 434 
 435     bool status_change = false;
 436 
 437     toIEWIndex = 0;
 438 
 439     sortInsts();
 440 
 441     list<ThreadID>::iterator threads = activeThreads->begin();
 442     list<ThreadID>::iterator end = activeThreads->end();
 443 
 444     // Check stall and squash signals.
 445     while (threads != end) {
 446         ThreadID tid = *threads++;
 447 
 448         DPRINTF(Rename, "Processing [tid:%i]\n", tid);
 449 
 450         status_change = checkSignalsAndUpdate(tid) || status_change;
 451 
 452         rename(status_change, tid);
 453     }
 454 
 455     if (status_change) {
 456         updateStatus();
 457     }
 458 
 459     if (wroteToTimeBuffer) {
 460         DPRINTF(Activity, "Activity this cycle.\n");
 461         cpu->activityThisCycle();
 462     }
 463 
 464     threads = activeThreads->begin();
 465 
 466     while (threads != end) {
 467         ThreadID tid = *threads++;
 468 
 469         // If we committed this cycle then doneSeqNum will be > 0
 470         if (fromCommit->commitInfo[tid].doneSeqNum != 0 &&
 471             !fromCommit->commitInfo[tid].squash &&
 472             renameStatus[tid] != Squashing) {
 473 
 474             removeFromHistory(fromCommit->commitInfo[tid].doneSeqNum,
 475                                   tid);
 476         }
 477     }
 478 
 479     // @todo: make into updateProgress function
 480     for (ThreadID tid = 0; tid < numThreads; tid++) {
 481         instsInProgress[tid] -= fromIEW->iewInfo[tid].dispatched;
 482         loadsInProgress[tid] -= fromIEW->iewInfo[tid].dispatchedToLQ;
 483         storesInProgress[tid] -= fromIEW->iewInfo[tid].dispatchedToSQ;
 484         assert(loadsInProgress[tid] >= 0);
 485         assert(storesInProgress[tid] >= 0);
 486         assert(instsInProgress[tid] >=0);
 487     }
 488 
 489 }
```

### sortInsts
```cpp
 836 template <class Impl>
 837 void
 838 DefaultRename<Impl>::sortInsts()
 839 {
 840     int insts_from_decode = fromDecode->size;
 841     for (int i = 0; i < insts_from_decode; ++i) {
 842         const DynInstPtr &inst = fromDecode->insts[i];
 843         insts[inst->threadNumber].push_back(inst);
 844 #if TRACING_ON
 845         if (DTRACE(O3PipeView)) {
 846             inst->renameTick = curTick() - inst->fetchTick;
 847         }
 848 #endif
 849     }
 850 }
```
Because the register maintains all instructions 
regardless of origin of the instructions (initiated by which thread), 
it should sort instructions based on the thread 
that instantiated the instruction. 
For that purpose, each instruction maintains information 
representing which thread is the owner of that instruction. 


### checkSignalsAndUpdate
```cpp
1331 template <class Impl>
1332 bool
1333 DefaultRename<Impl>::checkSignalsAndUpdate(ThreadID tid)
1334 {
1335     // Check if there's a squash signal, squash if there is
1336     // Check stall signals, block if necessary.
1337     // If status was blocked
1338     //     check if stall conditions have passed
1339     //         if so then go to unblocking
1340     // If status was Squashing
1341     //     check if squashing is not high.  Switch to running this cycle.
1342     // If status was serialize stall
1343     //     check if ROB is empty and no insts are in flight to the ROB
1344 
1345     readFreeEntries(tid);
1346     readStallSignals(tid);
1347 
1348     if (fromCommit->commitInfo[tid].squash) {
1349         DPRINTF(Rename, "[tid:%i] Squashing instructions due to squash from "
1350                 "commit.\n", tid);
1351 
1352         squash(fromCommit->commitInfo[tid].doneSeqNum, tid);
1353 
1354         return true;
1355     }
1356 
1357     if (checkStall(tid)) {
1358         return block(tid);
1359     }
1360 
1361     if (renameStatus[tid] == Blocked) {
1362         DPRINTF(Rename, "[tid:%i] Done blocking, switching to unblocking.\n",
1363                 tid);
1364 
1365         renameStatus[tid] = Unblocking;
1366 
1367         unblock(tid);
1368 
1369         return true;
1370     }
1371 
1372     if (renameStatus[tid] == Squashing) {
1373         // Switch status to running if rename isn't being told to block or
1374         // squash this cycle.
1375         if (resumeSerialize) {
1376             DPRINTF(Rename,
1377                     "[tid:%i] Done squashing, switching to serialize.\n", tid);
1378 
1379             renameStatus[tid] = SerializeStall;
1380             return true;
1381         } else if (resumeUnblocking) {
1382             DPRINTF(Rename,
1383                     "[tid:%i] Done squashing, switching to unblocking.\n",
1384                     tid);
1385             renameStatus[tid] = Unblocking;
1386             return true;
1387         } else {
1388             DPRINTF(Rename, "[tid:%i] Done squashing, switching to running.\n",
1389                     tid);
1390             renameStatus[tid] = Running;
1391             return false;
1392         }
1393     }
1394 
1395     if (renameStatus[tid] == SerializeStall) {
1396         // Stall ends once the ROB is free.
1397         DPRINTF(Rename, "[tid:%i] Done with serialize stall, switching to "
1398                 "unblocking.\n", tid);
1399 
1400         DynInstPtr serial_inst = serializeInst[tid];
1401 
1402         renameStatus[tid] = Unblocking;
1403 
1404         unblock(tid);
1405 
1406         DPRINTF(Rename, "[tid:%i] Processing instruction [%lli] with "
1407                 "PC %s.\n", tid, serial_inst->seqNum, serial_inst->pcState());
1408 
1409         // Put instruction into queue here.
1410         serial_inst->clearSerializeBefore();
1411 
1412         if (!skidBuffer[tid].empty()) {
1413             skidBuffer[tid].push_front(serial_inst);
1414         } else {
1415             insts[tid].push_front(serial_inst);
1416         }
1417 
1418         DPRINTF(Rename, "[tid:%i] Instruction must be processed by rename."
1419                 " Adding to front of list.\n", tid);
1420 
1421         serializeInst[tid] = NULL;
1422 
1423         return true;
1424     }
1425 
1426     // If we've reached this point, we have not gotten any signals that
1427     // cause rename to change its status.  Rename remains the same as before.
1428     return false;
1429 }
```

Note that most of the operation sequence of the checkSignalsAndUpdate 
is very similar to the checkSignalsAndUpdate of the decode stage.
It checks the stall and squash signal and execute associated code.
For the stall, it executes the block function. 
For the squash, it invokes the squash function.
However, in detail there are two noticeable differences
in the readFreeEntries and checkStall function.

```cpp
1295 template <class Impl>
1296 void
1297 DefaultRename<Impl>::readFreeEntries(ThreadID tid)
1298 {
1299     if (fromIEW->iewInfo[tid].usedIQ)
1300         freeEntries[tid].iqEntries = fromIEW->iewInfo[tid].freeIQEntries;
1301 
1302     if (fromIEW->iewInfo[tid].usedLSQ) {
1303         freeEntries[tid].lqEntries = fromIEW->iewInfo[tid].freeLQEntries;
1304         freeEntries[tid].sqEntries = fromIEW->iewInfo[tid].freeSQEntries;
1305     }
1306 
1307     if (fromCommit->commitInfo[tid].usedROB) {
1308         freeEntries[tid].robEntries =
1309             fromCommit->commitInfo[tid].freeROBEntries;
1310         emptyROB[tid] = fromCommit->commitInfo[tid].emptyROB;
1311     }
1312 
1313     DPRINTF(Rename, "[tid:%i] Free IQ: %i, Free ROB: %i, "
1314                     "Free LQ: %i, Free SQ: %i, FreeRM %i(%i %i %i %i %i)\n",
1315             tid,
1316             freeEntries[tid].iqEntries,
1317             freeEntries[tid].robEntries,
1318             freeEntries[tid].lqEntries,
1319             freeEntries[tid].sqEntries,
1320             renameMap[tid]->numFreeEntries(),
1321             renameMap[tid]->numFreeIntEntries(),
1322             renameMap[tid]->numFreeFloatEntries(),
1323             renameMap[tid]->numFreeVecEntries(),
1324             renameMap[tid]->numFreePredEntries(),
1325             renameMap[tid]->numFreeCCEntries());
1326 
1327     DPRINTF(Rename, "[tid:%i] %i instructions not yet in ROB\n",
1328             tid, instsInProgress[tid]);
1329 }
```

After the IEW stage executes and commit the instructions,
it should reports the Rename stage that 
it has used the allocated resources and
good to reassign them to other instructions 
for renaming. 
We will see how the freeEntries are retrieved
to its resource pool and reassigned to other instructions. 



```cpp
1263 template <class Impl>
1264 bool
1265 DefaultRename<Impl>::checkStall(ThreadID tid)
1266 {
1267     bool ret_val = false;
1268 
1269     if (stalls[tid].iew) {
1270         DPRINTF(Rename,"[tid:%i] Stall from IEW stage detected.\n", tid);
1271         ret_val = true;
1272     } else if (calcFreeROBEntries(tid) <= 0) {
1273         DPRINTF(Rename,"[tid:%i] Stall: ROB has 0 free entries.\n", tid);
1274         ret_val = true;
1275     } else if (calcFreeIQEntries(tid) <= 0) {
1276         DPRINTF(Rename,"[tid:%i] Stall: IQ has 0 free entries.\n", tid);
1277         ret_val = true;
1278     } else if (calcFreeLQEntries(tid) <= 0 && calcFreeSQEntries(tid) <= 0) {
1279         DPRINTF(Rename,"[tid:%i] Stall: LSQ has 0 free entries.\n", tid);
1280         ret_val = true;
1281     } else if (renameMap[tid]->numFreeEntries() <= 0) {
1282         DPRINTF(Rename,"[tid:%i] Stall: RenameMap has 0 free entries.\n", tid);
1283         ret_val = true;
1284     } else if (renameStatus[tid] == SerializeStall &&
1285                (!emptyROB[tid] || instsInProgress[tid])) {
1286         DPRINTF(Rename,"[tid:%i] Stall: Serialize stall and ROB is not "
1287                 "empty.\n",
1288                 tid);
1289         ret_val = true;
1290     }
1291 
1292     return ret_val;
1293 }
```

Regarding the stall, there could be lots of different reasons.
It might be because of the stall signal 
received from other stages
or the internal issues of the rename stage stalls itself 
due to lack of resources. 

## rename
```cpp
 491 template<class Impl>
 492 void
 493 DefaultRename<Impl>::rename(bool &status_change, ThreadID tid)
 494 {
 495     // If status is Running or idle,
 496     //     call renameInsts()
 497     // If status is Unblocking,
 498     //     buffer any instructions coming from decode
 499     //     continue trying to empty skid buffer
 500     //     check if stall conditions have passed
 501 
 502     if (renameStatus[tid] == Blocked) {
 503         ++renameBlockCycles;
 504     } else if (renameStatus[tid] == Squashing) {
 505         ++renameSquashCycles;
 506     } else if (renameStatus[tid] == SerializeStall) {
 507         ++renameSerializeStallCycles;
 508         // If we are currently in SerializeStall and resumeSerialize
 509         // was set, then that means that we are resuming serializing
 510         // this cycle.  Tell the previous stages to block.
 511         if (resumeSerialize) {
 512             resumeSerialize = false;
 513             block(tid);
 514             toDecode->renameUnblock[tid] = false;
 515         }
 516     } else if (renameStatus[tid] == Unblocking) {
 517         if (resumeUnblocking) {
 518             block(tid);
 519             resumeUnblocking = false;
 520             toDecode->renameUnblock[tid] = false;
 521         }
 522     }
 523 
 524     if (renameStatus[tid] == Running ||
 525         renameStatus[tid] == Idle) {
 526         DPRINTF(Rename,
 527                 "[tid:%i] "
 528                 "Not blocked, so attempting to run stage.\n",
 529                 tid);
 530 
 531         renameInsts(tid);
 532     } else if (renameStatus[tid] == Unblocking) {
 533         renameInsts(tid);
 534 
 535         if (validInsts()) {
 536             // Add the current inputs to the skid buffer so they can be
 537             // reprocessed when this stage unblocks.
 538             skidInsert(tid);
 539         }
 540 
 541         // If we switched over to blocking, then there's a potential for
 542         // an overall status change.
 543         status_change = unblock(tid) || status_change || blockThisCycle;
 544     }
 545 }
```

When there is no stall or blocking, 
now it can rename the instructions 
decoded by the decode stage one by one.
When the current renameStatus is Running or Idle, it will invoke 
renameInsts function to rename the instructions 
Also, when the renameStatus is Unblocking,
which means the rename stage is recovered from the Blocking status, 
it should also invokes the renameInsts function. 

### renameInsts: the main rename function 
The most of the rename function is done by the renameInsts function. 
Although it is pretty complicated, let's take a look at the details.

```cpp
 547 template <class Impl>
 548 void
 549 DefaultRename<Impl>::renameInsts(ThreadID tid)
 550 {
 551     // Instructions can be either in the skid buffer or the queue of
 552     // instructions coming from decode, depending on the status.
 553     int insts_available = renameStatus[tid] == Unblocking ?
 554         skidBuffer[tid].size() : insts[tid].size();
 555 
 556     // Check the decode queue to see if instructions are available.
 557     // If there are no available instructions to rename, then do nothing.
 558     if (insts_available == 0) {
 559         DPRINTF(Rename, "[tid:%i] Nothing to do, breaking out early.\n",
 560                 tid);
 561         // Should I change status to idle?
 562         ++renameIdleCycles;
 563         return;
 564     } else if (renameStatus[tid] == Unblocking) {
 565         ++renameUnblockCycles;
 566     } else if (renameStatus[tid] == Running) {
 567         ++renameRunCycles;
 568     }
 ```

First, it checks the current status of the rename stage. 
If the current status is Unblock, it should fetches instructions from 
the skidBuffer instead of the insts buffer. 
Also, even though it is running or idle status, 
it might not have available instructions because of stall, squash, or 
waiting until the previous stage's processing to be finished. 
Therefore, it first checks whether the instructions are available 
at the current clock cycle. 

### Checking ROB and IQ space 
```cpp
 570     // Will have to do a different calculation for the number of free
 571     // entries.
 572     int free_rob_entries = calcFreeROBEntries(tid);
 573     int free_iq_entries  = calcFreeIQEntries(tid);
 574     int min_free_entries = free_rob_entries;
 575 
 576     FullSource source = ROB;
 577 
 578     if (free_iq_entries < min_free_entries) {
 579         min_free_entries = free_iq_entries;
 580         source = IQ;
 581     }
 582 
 583     // Check if there's any space left.
 584     if (min_free_entries <= 0) {
 585         DPRINTF(Rename,
 586                 "[tid:%i] Blocking due to no free ROB/IQ/ entries.\n"
 587                 "ROB has %i free entries.\n"
 588                 "IQ has %i free entries.\n",
 589                 tid, free_rob_entries, free_iq_entries);
 590 
 591         blockThisCycle = true;
 592 
 593         block(tid);
 594 
 595         incrFullStat(source);
 596 
 597         return;
 598     } else if (min_free_entries < insts_available) {
 599         DPRINTF(Rename,
 600                 "[tid:%i] "
 601                 "Will have to block this cycle. "
 602                 "%i insts available, "
 603                 "but only %i insts can be renamed due to ROB/IQ/LSQ limits.\n",
 604                 tid, insts_available, min_free_entries);
 605 
 606         insts_available = min_free_entries;
 607 
 608         blockThisCycle = true;
 609 
 610         incrFullStat(source);
 611     }
 ```

It needs to consider ROB and instruction queue entries 
before the renaming. 
When there is no space, it should stall right a way.
However, if those entries are partially available,
part of the instructions accessible by the rename stage 
should be processed first. 
Because it still has some resources to process 
parts of the instructions,
it postpone stall later
(blockThisCycle = true).

### Checking serialization
```cpp
 613     InstQueue &insts_to_rename = renameStatus[tid] == Unblocking ?
 614         skidBuffer[tid] : insts[tid];
 615 
 616     DPRINTF(Rename,
 617             "[tid:%i] "
 618             "%i available instructions to send iew.\n",
 619             tid, insts_available);
 620 
 621     DPRINTF(Rename,
 622             "[tid:%i] "
 623             "%i insts pipelining from Rename | "
 624             "%i insts dispatched to IQ last cycle.\n",
 625             tid, instsInProgress[tid], fromIEW->iewInfo[tid].dispatched);
 626 
 627     // Handle serializing the next instruction if necessary.
 628     if (serializeOnNextInst[tid]) {
 629         if (emptyROB[tid] && instsInProgress[tid] == 0) {
 630             // ROB already empty; no need to serialize.
 631             serializeOnNextInst[tid] = false;
 632         } else if (!insts_to_rename.empty()) {
 633             insts_to_rename.front()->setSerializeBefore();
 634         }
 635     }
```

It also manages serializing instructions and generate stalls 
to enforce serialization operation. 
To this end, 
it provides associated functions and fields.
I will not cover the details here 
because they are utilized later when each instruction is processed
by the rename stage's main loop,

### Checking availability of the LQ and SQ
```cpp
 637     int renamed_insts = 0;
 638 
 639     while (insts_available > 0 &&  toIEWIndex < renameWidth) {
 640         DPRINTF(Rename, "[tid:%i] Sending instructions to IEW.\n", tid);
 641 
 642         assert(!insts_to_rename.empty());
 643 
 644         DynInstPtr inst = insts_to_rename.front();
 645 
 646         //For all kind of instructions, check ROB and IQ first
 647         //For load instruction, check LQ size and take into account the inflight loads
 648         //For store instruction, check SQ size and take into account the inflight stores
 649 
 650         if (inst->isLoad()) {
 651             if (calcFreeLQEntries(tid) <= 0) {
 652                 DPRINTF(Rename, "[tid:%i] Cannot rename due to no free LQ\n");
 653                 source = LQ;
 654                 incrFullStat(source);
 655                 break;
 656             }
 657         }
 658 
 659         if (inst->isStore() || inst->isAtomic()) {
 660             if (calcFreeSQEntries(tid) <= 0) {
 661                 DPRINTF(Rename, "[tid:%i] Cannot rename due to no free SQ\n");
 662                 source = SQ;
 663                 incrFullStat(source);
 664                 break;
 665             }
 666         }
 ```
Now we will take a look at the main loop of the rename stage.
It traverse all instructions stored in the insts_to_rename. 
Note that this can contain the Insts or the skidBuffer 
depending on the status of the current rename stage. 
Although we already checked 
the availability of IQ and ROB,
rename stage further checks 
the availability of the LoadQueue (LQ) and StoreQueue (SQ)
if the instruction is memory related operation.
Note that issuing memory operation will consume 
one entry from the corresponding queue.
If the LQ or SQ is full, then set the source as LQ or SQ 
to let the rest of the decode stage to know that 
the instruction cannot be issued to the next stage 
due to the lack of LQ or SQ and break (For statistics). 


### Consume one instruction and check register availability 
 ```cpp
 668         insts_to_rename.pop_front();
 669 
 670         if (renameStatus[tid] == Unblocking) {
 671             DPRINTF(Rename,
 672                     "[tid:%i] "
 673                     "Removing [sn:%llu] PC:%s from rename skidBuffer\n",
 674                     tid, inst->seqNum, inst->pcState());
 675         }
 676 
 677         if (inst->isSquashed()) {
 678             DPRINTF(Rename,
 679                     "[tid:%i] "
 680                     "instruction %i with PC %s is squashed, skipping.\n",
 681                     tid, inst->seqNum, inst->pcState());
 682 
 683             ++renameSquashedInsts;
 684 
 685             // Decrement how many instructions are available.
 686             --insts_available;
 687 
 688             continue;
 689         }
 690 
 691         DPRINTF(Rename,
 692                 "[tid:%i] "
 693                 "Processing instruction [sn:%llu] with PC %s.\n",
 694                 tid, inst->seqNum, inst->pcState());
 695 
 696         // Check here to make sure there are enough destination registers
 697         // to rename to.  Otherwise block.
 698         if (!renameMap[tid]->canRename(inst->numIntDestRegs(),
 699                                        inst->numFPDestRegs(),
 700                                        inst->numVecDestRegs(),
 701                                        inst->numVecElemDestRegs(),
 702                                        inst->numVecPredDestRegs(),
 703                                        inst->numCCDestRegs())) {
 704             DPRINTF(Rename,
 705                     "Blocking due to "
 706                     " lack of free physical registers to rename to.\n");
 707             blockThisCycle = true;
 708             insts_to_rename.push_front(inst);
 709             ++renameFullRegistersEvents;
 710 
 711             break;
 712         }
 ```
After it is guaranteed that the resources 
such as ROB, IQ, LQ, SQ are enough
to rename new instruction,
it consumes one instruction from the buffer (Line 668).
However, if there are not enough physical registers 
to rename the instruction's operands, 
then it should not be consumed.

## renameMap 
*gem5/src/cpu/o3/cpu.hh*
```cpp
583     /** The rename map. */
584     typename CPUPolicy::RenameMap renameMap[Impl::MaxThreads];
```
*gem5/src/cpu/o3/cpu_policy.hh*
```cpp
 60 template<class Impl>
 61 struct SimpleCPUPolicy
 62 {
 63     /** Typedef for the freelist of registers. */
 64     typedef UnifiedFreeList FreeList;
 65     /** Typedef for the rename map. */
 66     typedef UnifiedRenameMap RenameMap;
```
The renameMap contains all the hardware registers 
accessible by the processor. 
For example, 
even though the ISA has only handful of registers, 
in the backbone, 
there are lots of registers to execute instructions. 
The O3 CPU utilize the **UnifiedRenameMap**. 
Let's take a look at the details.

### UnifiedRenameMap has different types of SimpleRenameMaps
```cpp
163 /**
164  * Unified register rename map for all classes of registers.  Wraps a
165  * set of class-specific rename maps.  Methods that do not specify a
166  * register class (e.g., rename()) take register ids,
167  * while methods that do specify a register class (e.g., renameInt())
168  * take register indices.
169  */
170 class UnifiedRenameMap
171 {
172   private:
173     static constexpr uint32_t NVecElems = TheISA::NumVecElemPerVecReg;
174     using VecReg = TheISA::VecReg;
175     using VecPredReg = TheISA::VecPredReg;
176 
177     /** The integer register rename map */
178     SimpleRenameMap intMap;
179 
180     /** The floating-point register rename map */
181     SimpleRenameMap floatMap;
182 
183     /** The condition-code register rename map */
184     SimpleRenameMap ccMap;
185 
186     /** The vector register rename map */
187     SimpleRenameMap vecMap;
188 
189     /** The vector element register rename map */
190     SimpleRenameMap vecElemMap;
191 
192     /** The predicate register rename map */
193     SimpleRenameMap predMap;
194 
195     using VecMode = Enums::VecRegRenameMode;
196     VecMode vecMode;
```
The renameMap used by the O3 is 
just a wrapper of the renameMap of each types of registers. 
As shown in the above class definition, 
it contains integer, float, vector, and other types of registes

```cpp
 237         renameMap[tid].init(&regFile, TheISA::ZeroReg, fpZeroReg,
 238                             &freeList, vecMode);
 ......
 241     // Initialize rename map to assign physical registers to the
 242     // architectural registers for active threads only.
 243     for (ThreadID tid = 0; tid < active_threads; tid++) {
 244         for (RegIndex ridx = 0; ridx < TheISA::NumIntRegs; ++ridx) {
 245             // Note that we can't use the rename() method because we don't
 246             // want special treatment for the zero register at this point
 247             PhysRegIdPtr phys_reg = freeList.getIntReg();
 248             renameMap[tid].setEntry(RegId(IntRegClass, ridx), phys_reg);
 249             commitRenameMap[tid].setEntry(RegId(IntRegClass, ridx), phys_reg);
 250         }
 251 
 252         for (RegIndex ridx = 0; ridx < TheISA::NumFloatRegs; ++ridx) {
 253             PhysRegIdPtr phys_reg = freeList.getFloatReg();
 254             renameMap[tid].setEntry(RegId(FloatRegClass, ridx), phys_reg);
 255             commitRenameMap[tid].setEntry(
 256                     RegId(FloatRegClass, ridx), phys_reg);
 257         }
 258 
 259         /* Here we need two 'interfaces' the 'whole register' and the
 260          * 'register element'. At any point only one of them will be
 261          * active. */
 262         if (vecMode == Enums::Full) {
 263             /* Initialize the full-vector interface */
 264             for (RegIndex ridx = 0; ridx < TheISA::NumVecRegs; ++ridx) {
 265                 RegId rid = RegId(VecRegClass, ridx);
 266                 PhysRegIdPtr phys_reg = freeList.getVecReg();
 267                 renameMap[tid].setEntry(rid, phys_reg);
 268                 commitRenameMap[tid].setEntry(rid, phys_reg);
 269             }
 270         } else {
 271             /* Initialize the vector-element interface */
 272             for (RegIndex ridx = 0; ridx < TheISA::NumVecRegs; ++ridx) {
 273                 for (ElemIndex ldx = 0; ldx < TheISA::NumVecElemPerVecReg;
 274                         ++ldx) {
 275                     RegId lrid = RegId(VecElemClass, ridx, ldx);
 276                     PhysRegIdPtr phys_elem = freeList.getVecElem();
 277                     renameMap[tid].setEntry(lrid, phys_elem);
 278                     commitRenameMap[tid].setEntry(lrid, phys_elem);
 279                 }
 280             }
 281         }
 282 
 283         for (RegIndex ridx = 0; ridx < TheISA::NumVecPredRegs; ++ridx) {
 284             PhysRegIdPtr phys_reg = freeList.getVecPredReg();
 285             renameMap[tid].setEntry(RegId(VecPredRegClass, ridx), phys_reg);
 286             commitRenameMap[tid].setEntry(
 287                     RegId(VecPredRegClass, ridx), phys_reg);
 288         }
 289 
 290         for (RegIndex ridx = 0; ridx < TheISA::NumCCRegs; ++ridx) {
 291             PhysRegIdPtr phys_reg = freeList.getCCReg();
 292             renameMap[tid].setEntry(RegId(CCRegClass, ridx), phys_reg);
 293             commitRenameMap[tid].setEntry(RegId(CCRegClass, ridx), phys_reg);
 294         }
 295     }
 296 
 297     rename.setRenameMap(renameMap);
```
The above code initialize all entries of the renameMap. 
When the setEntry is invoked through the UnifiedRenameMap, 
it invokes setEntry function of the SimpleRenameMap
for all register types of the O3 CPU.

```cpp
302     /**
303      * Update rename map with a specific mapping.  Generally used to
304      * roll back to old mappings on a squash.  This version takes a
305      * flattened architectural register id and calls the
306      * appropriate class-specific rename table.
307      * @param arch_reg The architectural register to remap.
308      * @param phys_reg The physical register to remap it to.
309      */
310     void setEntry(const RegId& arch_reg, PhysRegIdPtr phys_reg)
311     {
312         switch (arch_reg.classValue()) {
313           case IntRegClass:
314             assert(phys_reg->isIntPhysReg());
315             return intMap.setEntry(arch_reg, phys_reg);
316 
317           case FloatRegClass:
318             assert(phys_reg->isFloatPhysReg());
319             return floatMap.setEntry(arch_reg, phys_reg);
320 
321           case VecRegClass:
322             assert(phys_reg->isVectorPhysReg());
323             assert(vecMode == Enums::Full);
324             return vecMap.setEntry(arch_reg, phys_reg);
325 
326           case VecElemClass:
327             assert(phys_reg->isVectorPhysElem());
328             assert(vecMode == Enums::Elem);
329             return vecElemMap.setEntry(arch_reg, phys_reg);
330 
331           case VecPredRegClass:
332             assert(phys_reg->isVecPredPhysReg());
333             return predMap.setEntry(arch_reg, phys_reg);
334 
335           case CCRegClass:
336             assert(phys_reg->isCCPhysReg());
337             return ccMap.setEntry(arch_reg, phys_reg);
338 
339           case MiscRegClass:
340             // Misc registers do not actually rename, so don't change
341             // their mappings.  We end up here when a commit or squash
342             // tries to update or undo a hardwired misc reg nmapping,
343             // which should always be setting it to what it already is.
344             assert(phys_reg == lookup(arch_reg));
345             return;
346 
347           default:
348             panic("rename setEntry(): unknown reg class %s\n",
349                   arch_reg.className());
350         }
351     }
```

The setEntry inserts new entry to the renameMap. 
However, because UnifiedRenameMap is just a wrapper class 
consisting of multiple SimpleRenameMaps 
with different types of registers, 
it inserts an entry to associated SimpleRenameMaps object
based on the type of register. 

### canRename checks availability of the register resource. 
```cpp
 696         // Check here to make sure there are enough destination registers
 697         // to rename to.  Otherwise block.
 698         if (!renameMap[tid]->canRename(inst->numIntDestRegs(),
 699                                        inst->numFPDestRegs(),
 700                                        inst->numVecDestRegs(),
 701                                        inst->numVecElemDestRegs(),
 702                                        inst->numVecPredDestRegs(),
 703                                        inst->numCCDestRegs())) {
 704             DPRINTF(Rename,
 705                     "Blocking due to "
 706                     " lack of free physical registers to rename to.\n");
 707             blockThisCycle = true;
 708             insts_to_rename.push_front(inst);
 709             ++renameFullRegistersEvents;
 710
 711             break;
 712         }
```
Before the rename its registers, 
it first checks 
whether the current physical resources are available 

```cpp
    /**
     * Return whether there are enough registers to serve the request.
     */
    bool canRename(uint32_t intRegs, uint32_t floatRegs, uint32_t vectorRegs,
                   uint32_t vecElemRegs, uint32_t vecPredRegs,
                   uint32_t ccRegs) const
    {
        return intRegs <= intMap.numFreeEntries() &&
            floatRegs <= floatMap.numFreeEntries() &&
            vectorRegs <= vecMap.numFreeEntries() &&
            vecElemRegs <= vecElemMap.numFreeEntries() &&
            vecPredRegs <= predMap.numFreeEntries() &&
            ccRegs <= ccMap.numFreeEntries();
    }

```

## Handle serialization instruction 
If there is enough resources to rename instructions,
now it checks whether the current instruction should follow
serialization or barrier constraint. 

```cpp
 714         // Handle serializeAfter/serializeBefore instructions.
 715         // serializeAfter marks the next instruction as serializeBefore.
 716         // serializeBefore makes the instruction wait in rename until the ROB
 717         // is empty.
 718 
 719         // In this model, IPR accesses are serialize before
 720         // instructions, and store conditionals are serialize after
 721         // instructions.  This is mainly due to lack of support for
 722         // out-of-order operations of either of those classes of
 723         // instructions.
 724         if ((inst->isIprAccess() || inst->isSerializeBefore()) &&
 725             !inst->isSerializeHandled()) {
 726             DPRINTF(Rename, "Serialize before instruction encountered.\n");
 727 
 728             if (!inst->isTempSerializeBefore()) {
 729                 renamedSerializing++;
 730                 inst->setSerializeHandled();
 731             } else {
 732                 renamedTempSerializing++;
 733             }
 734 
 735             // Change status over to SerializeStall so that other stages know
 736             // what this is blocked on.
 737             renameStatus[tid] = SerializeStall;
 738 
 739             serializeInst[tid] = inst;
 740 
 741             blockThisCycle = true;
 742 
 743             break;
 744         } else if ((inst->isStoreConditional() || inst->isSerializeAfter()) &&
 745                    !inst->isSerializeHandled()) {
 746             DPRINTF(Rename, "Serialize after instruction encountered.\n");
 747 
 748             renamedSerializing++;
 749 
 750             inst->setSerializeHandled();
 751 
 752             serializeAfter(insts_to_rename, tid);
 753         }
 ```

**StaticInst** class has flags member field 
which represents properties of one instruction 
such as serializing, memory barrier, load operation, etc. 
Also, it has corresponding get methods to retrieve those flags 
from the StaticInst objects. 
Remember that all the instructions 
we generated at the fetch stage 
was the object of the StaticInst. 
Also, its flags are set 
based on the implementation of the microops of different architectures. 
Therefore, by checking the isSerializeAfter and isSerializeBefore 
of the current static instruction,
the rename stage determines 
whether it should block the stage or moves to the next instruction. 
Note that the serializeBefore means that 
the current instruction should be blocked, but 
the serializeAfter means that 
the next instruction after current instruction should be blocked. 
Therefore, by invoking serializeAfter function, 
it makes the next instruction have IsSerializeBefore flag. 

```cpp
1431 template<class Impl>
1432 void
1433 DefaultRename<Impl>::serializeAfter(InstQueue &inst_list, ThreadID tid)
1434 {
1435     if (inst_list.empty()) {
1436         // Mark a bit to say that I must serialize on the next instruction.
1437         serializeOnNextInst[tid] = true;
1438         return;
1439     }
1440 
1441     // Set the next instruction as serializing.
1442     inst_list.front()->setSerializeBefore();
1443 }
```

Note that there are two cases. When the current instruction is serializeBefore and the last one 
in the queue, then it should block the next instruction until all the instructions to be executed. 
However, because we don't know which instructions will be passed to the rename stage, 
it just sets the serializeOnNextInst as true to make the rename stage make the 
first instruction processed by the rename stage at the next cycle to be blocked.
If the buffer still has following instruction, then it just set the next instruction as 
serializeBefore.

```cpp
 627     // Handle serializing the next instruction if necessary.
 628     if (serializeOnNextInst[tid]) {
 629         if (emptyROB[tid] && instsInProgress[tid] == 0) {
 630             // ROB already empty; no need to serialize.
 631             serializeOnNextInst[tid] = false;
 632         } else if (!insts_to_rename.empty()) {
 633             insts_to_rename.front()->setSerializeBefore();
 634         }
 635     }
```
As shown in the above code (Line 632-633), 
when the next renameInsts function is executed at the next clock cycle, 
it checks whether the serializeOnNextInst has been set, 
which means that the last instruction was serializeAfter instruction 
at the previous clock cycle. In that case it sets the current instruction
to be renamed as serializeBefore to make serialization. 

### X86 in GEM5 provides macro setting serialization 
```cpp
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
```
For macroop definition, when .serialize_before or .serialize_after keyword is found 
in the definition, the GEM5 parser invokes the self.serializeBefore and self.serializeAfter 
function respectively to set the serialize_before and serialize_after memeber field as true.

```cpp
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
```
When the macroop definition is automatically generated, it checks those two flags and 
set IsSerializeBefore to the first microop and IsSerializeAfter to the last microop 
consisting of the macroop. 

## Rename registers and pass the renamed instruction to the next stage
After handling serialization instruction, it should rename 
registers of the instruction. 
```cpp
 755         renameSrcRegs(inst, inst->threadNumber);
 756 
 757         renameDestRegs(inst, inst->threadNumber);
 758 
 759         if (inst->isAtomic() || inst->isStore()) {
 760             storesInProgress[tid]++;
 761         } else if (inst->isLoad()) {
 762             loadsInProgress[tid]++;
 763         }
 764 
 765         ++renamed_insts;
 766         // Notify potential listeners that source and destination registers for
 767         // this instruction have been renamed.
 768         ppRename->notify(inst);
 769 
 770         // Put instruction in rename queue.
 771         toIEW->insts[toIEWIndex] = inst;
 772         ++(toIEW->size);
 773 
 774         // Increment which instruction we're on.
 775         ++toIEWIndex;
 776 
 777         // Decrement how many instructions are available.
 778         --insts_available;
 779     }
```

### renameSrcRegs
```cpp
1064 template <class Impl>
1065 inline void
1066 DefaultRename<Impl>::renameSrcRegs(const DynInstPtr &inst, ThreadID tid)
1067 {
1068     ThreadContext *tc = inst->tcBase();
1069     RenameMap *map = renameMap[tid];
1070     unsigned num_src_regs = inst->numSrcRegs();
1071 
1072     // Get the architectual register numbers from the source and
1073     // operands, and redirect them to the right physical register.
1074     for (int src_idx = 0; src_idx < num_src_regs; src_idx++) {
1075         const RegId& src_reg = inst->srcRegIdx(src_idx);
1076         PhysRegIdPtr renamed_reg;
1077 
1078         renamed_reg = map->lookup(tc->flattenRegId(src_reg));
1079         switch (src_reg.classValue()) {
1080           case IntRegClass:
1081             intRenameLookups++;
1082             break;
1083           case FloatRegClass:
1084             fpRenameLookups++;
1085             break;
1086           case VecRegClass:
1087           case VecElemClass:
1088             vecRenameLookups++;
1089             break;
1090           case VecPredRegClass:
1091             vecPredRenameLookups++;
1092             break;
1093           case CCRegClass:
1094           case MiscRegClass:
1095             break;
1096 
1097           default:
1098             panic("Invalid register class: %d.", src_reg.classValue());
1099         }
1100 
1101         DPRINTF(Rename,
1102                 "[tid:%i] "
1103                 "Looking up %s arch reg %i, got phys reg %i (%s)\n",
1104                 tid, src_reg.className(),
1105                 src_reg.index(), renamed_reg->index(),
1106                 renamed_reg->className());
1107 
1108         inst->renameSrcReg(src_idx, renamed_reg);
1109 
1110         // See if the register is ready or not.
1111         if (scoreboard->getReg(renamed_reg)) {
1112             DPRINTF(Rename,
1113                     "[tid:%i] "
1114                     "Register %d (flat: %d) (%s) is ready.\n",
1115                     tid, renamed_reg->index(), renamed_reg->flatIndex(),
1116                     renamed_reg->className());
1117 
1118             inst->markSrcRegReady(src_idx);
1119         } else {
1120             DPRINTF(Rename,
1121                     "[tid:%i] "
1122                     "Register %d (flat: %d) (%s) is not ready.\n",
1123                     tid, renamed_reg->index(), renamed_reg->flatIndex(),
1124                     renamed_reg->className());
1125         }
1126 
1127         ++renameRenameLookups;
1128     }
1129 }
```
The main operation of the renameSrcRegs are lookingup the register map 
if the architecture register used by the current instruction's source 
has been renamed to the another physical register. 

### lookup renameMap to find physical register if it has been renamed 
```cpp
 66 class SimpleRenameMap
 67 {
......
122     /**
123      * Look up the physical register mapped to an architectural register.
124      * @param arch_reg The architectural register to look up.
125      * @return The physical register it is currently mapped to.
126      */
127     PhysRegIdPtr lookup(const RegId& arch_reg) const
128     {
129         assert(arch_reg.flatIndex() <= map.size());
130         return map[arch_reg.flatIndex()];
131     }
......
170 class UnifiedRenameMap
171 {
......
261     /**
262      * Look up the physical register mapped to an architectural register.
263      * This version takes a flattened architectural register id
264      * and calls the appropriate class-specific rename table.
265      * @param arch_reg The architectural register to look up.
266      * @return The physical register it is currently mapped to.
267      */
268     PhysRegIdPtr lookup(const RegId& arch_reg) const
269     {
270         switch (arch_reg.classValue()) {
271           case IntRegClass:
272             return intMap.lookup(arch_reg);
273 
274           case FloatRegClass:
275             return  floatMap.lookup(arch_reg);
276 
277           case VecRegClass:
278             assert(vecMode == Enums::Full);
279             return  vecMap.lookup(arch_reg);
280 
281           case VecElemClass:
282             assert(vecMode == Enums::Elem);
283             return  vecElemMap.lookup(arch_reg);
284 
285           case VecPredRegClass:
286             return predMap.lookup(arch_reg);
287 
288           case CCRegClass:
289             return ccMap.lookup(arch_reg);
290 
291           case MiscRegClass:
292             // misc regs aren't really renamed, they keep the same
293             // mapping throughout the execution.
294             return regFile->getMiscRegId(arch_reg.flatIndex());
295 
296           default:
297             panic("rename lookup(): unknown reg class %s\n",
298                   arch_reg.className());
299         }
300     }
```
If it has been renamed before, the **lookup** function returns 
actual physical register to which the architecture register has been mapped.
The map used in the rename stage is UnifiedRenameMap and contains 
multiple SimpleRenameMap with the various register type.
Therefore, it first invokes the lookup function of the UnifiedRenameMap,
and further invokes the lookup function of the SimpleRenameMap 
depending on the register type that we are trying to rename. 

### check scoreboard
After the lookup, it checks the scoreboard if the target register is ready to be read. 
Because O3 is out-of-order processor, and renaming register is utilized 
to eliminate register dependency such as write after read, scoreboard let the processor
know when the register is ready to be accessed. 
Particularly, the getReg interface of the scoreboard 
can be utilized to check specific register is currently available.
If it returns true, the source register is available to be read, so 
it sets the instruction marks the source register is ready (markSrcRegReady).
However, if the getReg returns false, it means that the source register is not available 
at this cycle, so it should not set the flag and make the instruction to wait 
in the next issue stage until the register is ready. 
The scoreboard and its interfaces will be described in the [below section]().

### renameDestRegs 
```cpp
1131 template <class Impl>
1132 inline void
1133 DefaultRename<Impl>::renameDestRegs(const DynInstPtr &inst, ThreadID tid)
1134 {
1135     ThreadContext *tc = inst->tcBase();
1136     RenameMap *map = renameMap[tid];
1137     unsigned num_dest_regs = inst->numDestRegs();
1138 
1139     // Rename the destination registers.
1140     for (int dest_idx = 0; dest_idx < num_dest_regs; dest_idx++) {
1141         const RegId& dest_reg = inst->destRegIdx(dest_idx);
1142         typename RenameMap::RenameInfo rename_result;
1143 
1144         RegId flat_dest_regid = tc->flattenRegId(dest_reg);
1145         flat_dest_regid.setNumPinnedWrites(dest_reg.getNumPinnedWrites());
1146 
1147         rename_result = map->rename(flat_dest_regid);
1148 
1149         inst->flattenDestReg(dest_idx, flat_dest_regid);
1150 
1151         scoreboard->unsetReg(rename_result.first);
1152 
1153         DPRINTF(Rename,
1154                 "[tid:%i] "
1155                 "Renaming arch reg %i (%s) to physical reg %i (%i).\n",
1156                 tid, dest_reg.index(), dest_reg.className(),
1157                 rename_result.first->index(),
1158                 rename_result.first->flatIndex());
1159 
1160         // Record the rename information so that a history can be kept.
1161         RenameHistory hb_entry(inst->seqNum, flat_dest_regid,
1162                                rename_result.first,
1163                                rename_result.second);
1164 
1165         historyBuffer[tid].push_front(hb_entry);
1166 
1167         DPRINTF(Rename, "[tid:%i] [sn:%llu] "
1168                 "Adding instruction to history buffer (size=%i).\n",
1169                 tid,(*historyBuffer[tid].begin()).instSeqNum,
1170                 historyBuffer[tid].size());
1171 
1172         // Tell the instruction to rename the appropriate destination
1173         // register (dest_idx) to the new physical register
1174         // (rename_result.first), and record the previous physical
1175         // register that the same logical register was renamed to
1176         // (rename_result.second).
1177         inst->renameDestReg(dest_idx,
1178                             rename_result.first,
1179                             rename_result.second);
1180 
1181         ++renameRenamedOperands;
1182     }
1183 }
```
Basically, the renameDestRegs function is similar to the renameSrcRegs in such a way that 
it renames the registers. However, renaming destination register incurs some changes 
on the register map and the scoreboard. 

### rename: renames specific register to the other
```cpp
221     /**
222      * Tell rename map to get a new free physical register to remap
223      * the specified architectural register. This version takes a
224      * RegId and reads the  appropriate class-specific rename table.
225      * @param arch_reg The architectural register id to remap.
226      * @return A RenameInfo pair indicating both the new and previous
227      * physical registers.
228      */
229     RenameInfo rename(const RegId& arch_reg)
230     {
231         switch (arch_reg.classValue()) {
232           case IntRegClass:
233             return intMap.rename(arch_reg);
234           case FloatRegClass:
235             return floatMap.rename(arch_reg);
236           case VecRegClass:
237             assert(vecMode == Enums::Full);
238             return vecMap.rename(arch_reg);
239           case VecElemClass:
240             assert(vecMode == Enums::Elem);
241             return vecElemMap.rename(arch_reg);
242           case VecPredRegClass:
243             return predMap.rename(arch_reg);
244           case CCRegClass:
245             return ccMap.rename(arch_reg);
246           case MiscRegClass:
247             {
248             // misc regs aren't really renamed, just remapped
249             PhysRegIdPtr phys_reg = lookup(arch_reg);
250             // Set the new register to the previous one to keep the same
251             // mapping throughout the execution.
252             return RenameInfo(phys_reg, phys_reg);
253             }
254 
255           default:
256             panic("rename rename(): unknown reg class %s\n",
257                   arch_reg.className());
258         }
259     }
```
Instead of invoking lookup function of the register map, it invokes the rename function.


```cpp
 73 SimpleRenameMap::RenameInfo
 74 SimpleRenameMap::rename(const RegId& arch_reg)
 75 {
 76     PhysRegIdPtr renamed_reg;
 77     // Record the current physical register that is renamed to the
 78     // requested architected register.
 79     PhysRegIdPtr prev_reg = map[arch_reg.flatIndex()];
 80 
 81     if (arch_reg == zeroReg) {
 82         assert(prev_reg->isZeroReg());
 83         renamed_reg = prev_reg;
 84     } else if (prev_reg->getNumPinnedWrites() > 0) {
 85         // Do not rename if the register is pinned
 86         assert(arch_reg.getNumPinnedWrites() == 0);  // Prevent pinning the
 87                                                      // same register twice
 88         DPRINTF(Rename, "Renaming pinned reg, numPinnedWrites %d\n",
 89                 prev_reg->getNumPinnedWrites());
 90         renamed_reg = prev_reg;
 91         renamed_reg->decrNumPinnedWrites();
 92     } else {
 93         renamed_reg = freeList->getReg();
 94         map[arch_reg.flatIndex()] = renamed_reg;
 95         renamed_reg->setNumPinnedWrites(arch_reg.getNumPinnedWrites());
 96         renamed_reg->setNumPinnedWritesToComplete(
 97             arch_reg.getNumPinnedWrites() + 1);
 98     }
 99 
100     DPRINTF(Rename, "Renamed reg %d to physical reg %d (%d) old mapping was"
101             " %d (%d)\n",
102             arch_reg, renamed_reg->flatIndex(), renamed_reg->flatIndex(),
103             prev_reg->flatIndex(), prev_reg->flatIndex());
104 
105     return RenameInfo(renamed_reg, prev_reg);
106 }
```

### Make the renamed register as not ready
it invokes unsetReg.




### Populating history buffer entry per destination register rename 
After the renaming is done (line 1161-1163),
it generates history entry for providing \TODO{is it for precise exception?? what purpose is it?}

```cpp
303     struct RenameHistory {
304         RenameHistory(InstSeqNum _instSeqNum, const RegId& _archReg,
305                       PhysRegIdPtr _newPhysReg,
306                       PhysRegIdPtr _prevPhysReg)
307             : instSeqNum(_instSeqNum), archReg(_archReg),
308               newPhysReg(_newPhysReg), prevPhysReg(_prevPhysReg)
309         {
310         }
311 
312         /** The sequence number of the instruction that renamed. */
313         InstSeqNum instSeqNum;
314         /** The architectural register index that was renamed. */
315         RegId archReg;
316         /** The new physical register that the arch. register is renamed to. */
317         PhysRegIdPtr newPhysReg;
318         /** The old physical register that the arch. register was renamed to.
319          */
320         PhysRegIdPtr prevPhysReg;
321     };                       
322 
323     /** A per-thread list of all destination register renames, used to either
324      * undo rename mappings or free old physical registers.
325      */
326     std::list<RenameHistory> historyBuffer[Impl::MaxThreads];
```

After renaming destination and source registers, 
it pushes the renamed instruction to the toIEW register. 

### End of the main loop
```cpp
 781     instsInProgress[tid] += renamed_insts;
 782     renameRenamedInsts += renamed_insts;
 783 
 784     // If we wrote to the time buffer, record this.
 785     if (toIEWIndex) {
 786         wroteToTimeBuffer = true;
 787     }
 788 
 789     // Check if there's any instructions left that haven't yet been renamed.
 790     // If so then block.
 791     if (insts_available) {
 792         blockThisCycle = true;
 793     }
 794 
 795     if (blockThisCycle) {
 796         block(tid);
 797         toDecode->renameUnblock[tid] = false;
 798     }
 799 }
```


## scoreboard
### scoreboard interface
*gem5/src/cpu/o3/scoreboard.hh*
```cpp
 46 /**
 47  * Implements a simple scoreboard to track which registers are
 48  * ready. This class operates on the unified physical register space,
 49  * because the different classes of registers do not need to be distinguished.
 50  * Registers being part of a fixed mapping are always considered ready.
 51  */
 52 class Scoreboard
 53 {
 54   private:
 55     /** The object name, for DPRINTF.  We have to declare this
 56      *  explicitly because Scoreboard is not a SimObject. */
 57     const std::string _name;
 58 
 59     /** Scoreboard of physical integer registers, saying whether or not they
 60      *  are ready. */
 61     std::vector<bool> regScoreBoard;
 62 
 63     /** The number of actual physical registers */
 64     unsigned M5_CLASS_VAR_USED numPhysRegs;
 65 
 66   public:
 67     /** Constructs a scoreboard.
 68      *  @param _numPhysicalRegs Number of physical registers.
 69      *  @param _numMiscRegs Number of miscellaneous registers.
 70      */
 71     Scoreboard(const std::string &_my_name,
 72                unsigned _numPhysicalRegs);
 73 
 74     /** Destructor. */
 75     ~Scoreboard() {}
 76 
 77     /** Returns the name of the scoreboard. */
 78     std::string name() const { return _name; };
 79 
 80     /** Checks if the register is ready. */
 81     bool getReg(PhysRegIdPtr phys_reg) const
 82     {
 83         assert(phys_reg->flatIndex() < numPhysRegs);
 84 
 85         if (phys_reg->isFixedMapping()) {
 86             // Fixed mapping regs are always ready
 87             return true;
 88         }
 89 
 90         bool ready = regScoreBoard[phys_reg->flatIndex()];
 91 
 92         if (phys_reg->isZeroReg())
 93             assert(ready);
 94 
 95         return ready;
 96     }
 97 
 98     /** Sets the register as ready. */
 99     void setReg(PhysRegIdPtr phys_reg)
100     {
101         assert(phys_reg->flatIndex() < numPhysRegs);
102 
103         if (phys_reg->isFixedMapping()) {
104             // Fixed mapping regs are always ready, ignore attempts to change
105             // that
106             return;
107         }
108 
109         DPRINTF(Scoreboard, "Setting reg %i (%s) as ready\n",
110                 phys_reg->index(), phys_reg->className());
111 
112         regScoreBoard[phys_reg->flatIndex()] = true;
113     }
114 
115     /** Sets the register as not ready. */
116     void unsetReg(PhysRegIdPtr phys_reg)
117     {
118         assert(phys_reg->flatIndex() < numPhysRegs);
119 
120         if (phys_reg->isFixedMapping()) {
121             // Fixed mapping regs are always ready, ignore attempts to
122             // change that
123             return;
124         }
125 
126         // zero reg should never be marked unready
127         if (phys_reg->isZeroReg())
128             return;
129 
130         regScoreBoard[phys_reg->flatIndex()] = false;
131     }
132 
133 };
```
Scoreboard is implemented as a simple vector (regScoreBoard) to indicate 
specific register is ready to be used or not. 
And it provide three interfaces to set or get the status 
of the specific register maintained by the scoreboard. 

### scoreboard used by the O3 CPU
*gem5/src/cpu/o3/cpu.hh*
```cpp
602     /** Integer Register Scoreboard */
603     Scoreboard scoreboard; 
```

*gem5/src/cpu/o3/cpu.cc*
```cpp
 218     rename.setScoreboard(&scoreboard);
 219     iew.setScoreboard(&scoreboard);
```

At the real hardware implementation, the scoreboard should be accessible by the 
multiple stages at the same time. However, because it is software emulation,
GEM5 doesn't provide port-wise emulation to service different modules at the same time.
Note that GEM5 executes in single thread and cannot be executed in multi-threads. 
Anyway, the scoreboard is accessed by two different stages in the O3CPU: rename and iew.


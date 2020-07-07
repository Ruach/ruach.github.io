---
layout: post
titile: "Pagetable walking and pagefault handling in Gem5"
categories: GEM5, TLB
---

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

# Cache receive 
```cpp
2510 bool
2511 BaseCache::MemSidePort::recvTimingResp(PacketPtr pkt)
2512 {
2513     cache->recvTimingResp(pkt);
2514     return true;
2515 }
```


## BaseCache::recvTimingResp 
```cpp
 419 void
 420 BaseCache::recvTimingResp(PacketPtr pkt)
 421 {
 422     assert(pkt->isResponse());
 423 
 424     // all header delay should be paid for by the crossbar, unless
 425     // this is a prefetch response from above
 426     panic_if(pkt->headerDelay != 0 && pkt->cmd != MemCmd::HardPFResp,
 427              "%s saw a non-zero packet delay\n", name());
 428 
 429     const bool is_error = pkt->isError();
 430 
 431     if (is_error) {
 432         DPRINTF(Cache, "%s: Cache received %s with error\n", __func__,
 433                 pkt->print());
 434     }
 435 
 436     DPRINTF(Cache, "%s: Handling response %s\n", __func__,
 437             pkt->print());
 438 
 439     // if this is a write, we should be looking at an uncacheable
 440     // write
 441     if (pkt->isWrite()) {
 442         assert(pkt->req->isUncacheable());
 443         handleUncacheableWriteResp(pkt);
 444         return;
 445     }
 446 
 447     // we have dealt with any (uncacheable) writes above, from here on
 448     // we know we are dealing with an MSHR due to a miss or a prefetch
 449     MSHR *mshr = dynamic_cast<MSHR*>(pkt->popSenderState());
 450     assert(mshr);
 451 
 452     if (mshr == noTargetMSHR) {
 453         // we always clear at least one target
 454         clearBlocked(Blocked_NoTargets);
 455         noTargetMSHR = nullptr;
 456     }
 457 
 458     // Initial target is used just for stats
 459     const QueueEntry::Target *initial_tgt = mshr->getTarget();
 460     const Tick miss_latency = curTick() - initial_tgt->recvTime;
 461     if (pkt->req->isUncacheable()) {
 462         assert(pkt->req->requestorId() < system->maxRequestors());
 463         stats.cmdStats(initial_tgt->pkt)
 464             .mshrUncacheableLatency[pkt->req->requestorId()] += miss_latency;
 465     } else {
 466         assert(pkt->req->requestorId() < system->maxRequestors());
 467         stats.cmdStats(initial_tgt->pkt)
 468             .mshrMissLatency[pkt->req->requestorId()] += miss_latency;
 469     }
```

## Filling the cache with the fetched data (recvTimingResp) 
```cpp
 471     PacketList writebacks;
 472 
 473     bool is_fill = !mshr->isForward &&
 474         (pkt->isRead() || pkt->cmd == MemCmd::UpgradeResp ||
 475          mshr->wasWholeLineWrite);
 476 
 477     // make sure that if the mshr was due to a whole line write then
 478     // the response is an invalidation
 479     assert(!mshr->wasWholeLineWrite || pkt->isInvalidate());
 480 
 481     CacheBlk *blk = tags->findBlock(pkt->getAddr(), pkt->isSecure());
 482 
 483     if (is_fill && !is_error) {
 484         DPRINTF(Cache, "Block for addr %#llx being updated in Cache\n",
 485                 pkt->getAddr());
 486 
 487         const bool allocate = (writeAllocator && mshr->wasWholeLineWrite) ?
 488             writeAllocator->allocate() : mshr->allocOnFill();
 489         blk = handleFill(pkt, blk, writebacks, allocate);
 490         assert(blk != nullptr);
 491         ppFill->notify(pkt);
 492     }
```
First of all, it needs to search the current cache to find out the block
mapped to the current request's address.


### handleFill
```cpp
1433 CacheBlk*
1434 BaseCache::handleFill(PacketPtr pkt, CacheBlk *blk, PacketList &writebacks,
1435                       bool allocate)
1436 {
1437     assert(pkt->isResponse());
1438     Addr addr = pkt->getAddr();
1439     bool is_secure = pkt->isSecure();
1440     const bool has_old_data = blk && blk->isValid();
1441     const std::string old_state = blk ? blk->print() : "";
1442 
1443     // When handling a fill, we should have no writes to this line.
1444     assert(addr == pkt->getBlockAddr(blkSize));
1445     assert(!writeBuffer.findMatch(addr, is_secure));
1446 
1447     if (!blk) {
1448         // better have read new data...
1449         assert(pkt->hasData() || pkt->cmd == MemCmd::InvalidateResp);
1450 
1451         // need to do a replacement if allocating, otherwise we stick
1452         // with the temporary storage
1453         blk = allocate ? allocateBlock(pkt, writebacks) : nullptr;
1454 
1455         if (!blk) {
1456             // No replaceable block or a mostly exclusive
1457             // cache... just use temporary storage to complete the
1458             // current request and then get rid of it
1459             blk = tempBlock;
1460             tempBlock->insert(addr, is_secure);
1461             DPRINTF(Cache, "using temp block for %#llx (%s)\n", addr,
1462                     is_secure ? "s" : "ns");
1463         }
1464     } else {
1465         // existing block... probably an upgrade
1466         // don't clear block status... if block is already dirty we
1467         // don't want to lose that
1468     }
```
When the blk is nullptr, 
it allocates new block 
depending on the allocate flag.
When the flat is set, it allocates new block in the cache 
by invoking allocateBlock function. Note that writebacks is passed 
together with the packet. When the cache has no slot for the 
new data, then it evicts the pre-allocated one and will be handled 
by the writebacks. 
If there is no require for allocating new block, 
it assigns tempBlock instead of allocating new one.
Note that it is required because the block is necessary in any case 
to process the current request. 

The allocate flag is determined mostly based on the inclusiveness of
current cache level. 
When current cache level is exclusive to the lower cache level,
it doesn't need to allocate cache line for the current cache level 
and just forward the request to the upper level.
Note that even for the exclusive cache, if one cache level is 
higher than the other, the request from more higher level cache 
or the memory should goes through the current cache level. 


### setCoherenceBits:???
```cpp
1469 
1470     // Block is guaranteed to be valid at this point
1471     assert(blk->isValid());
1472     assert(blk->isSecure() == is_secure);
1473     assert(regenerateBlkAddr(blk) == addr);
1474 
1475     blk->setCoherenceBits(CacheBlk::ReadableBit);
1476 
1477     // sanity check for whole-line writes, which should always be
1478     // marked as writable as part of the fill, and then later marked
1479     // dirty as part of satisfyRequest
1480     if (pkt->cmd == MemCmd::InvalidateResp) {
1481         assert(!pkt->hasSharers());
1482     }
1483 
1484     // here we deal with setting the appropriate state of the line,
1485     // and we start by looking at the hasSharers flag, and ignore the
1486     // cacheResponding flag (normally signalling dirty data) if the
1487     // packet has sharers, thus the line is never allocated as Owned
1488     // (dirty but not writable), and always ends up being either
1489     // Shared, Exclusive or Modified, see Packet::setCacheResponding
1490     // for more details
1491     if (!pkt->hasSharers()) {
1492         // we could get a writable line from memory (rather than a
1493         // cache) even in a read-only cache, note that we set this bit
1494         // even for a read-only cache, possibly revisit this decision
1495         blk->setCoherenceBits(CacheBlk::WritableBit);
1496 
1497         // check if we got this via cache-to-cache transfer (i.e., from a
1498         // cache that had the block in Modified or Owned state)
1499         if (pkt->cacheResponding()) {
1500             // we got the block in Modified state, and invalidated the
1501             // owners copy
1502             blk->setCoherenceBits(CacheBlk::DirtyBit);
1503 
1504             chatty_assert(!isReadOnly, "Should never see dirty snoop response "
1505                           "in read-only cache %s\n", name());
1506 
1507         }
1508     }
1509 
1510     DPRINTF(Cache, "Block addr %#llx (%s) moving from %s to %s\n",
1511             addr, is_secure ? "s" : "ns", old_state, blk->print());
1512 
```

### Filling the block and returning the filled block
```cpp
1513     // if we got new data, copy it in (checking for a read response
1514     // and a response that has data is the same in the end)
1515     if (pkt->isRead()) {
1516         // sanity checks
1517         assert(pkt->hasData());
1518         assert(pkt->getSize() == blkSize);
1519 
1520         updateBlockData(blk, pkt, has_old_data);
1521     }
1522     // The block will be ready when the payload arrives and the fill is done
1523     blk->setWhenReady(clockEdge(fillLatency) + pkt->headerDelay +
1524                       pkt->payloadDelay);
1525 
1526     return blk;
1527 }
```

```cpp
 694 void
 695 BaseCache::updateBlockData(CacheBlk *blk, const PacketPtr cpkt,
 696     bool has_old_data)
 697 {
 698     DataUpdate data_update(regenerateBlkAddr(blk), blk->isSecure());
 699     if (ppDataUpdate->hasListeners()) {
 700         if (has_old_data) {
 701             data_update.oldData = std::vector<uint64_t>(blk->data,
 702                 blk->data + (blkSize / sizeof(uint64_t)));
 703         }
 704     }
 705 
 706     // Actually perform the data update
 707     if (cpkt) {
 708         cpkt->writeDataToBlock(blk->data, blkSize);
 709     }
 710 
 711     if (ppDataUpdate->hasListeners()) {
 712         if (cpkt) {
 713             data_update.newData = std::vector<uint64_t>(blk->data,
 714                 blk->data + (blkSize / sizeof(uint64_t)));
 715         }
 716         ppDataUpdate->notify(data_update);
 717     }
 718 }
```
The actual data write is done by the updateBlockData function.
Because the received packet contains the actual data 
that should be filled in the cache block, 
it copies the data from the packet to the cache block.

```cpp
271     /**  
272      * Set tick at which block's data will be available for access. The new
273      * tick must be chronologically sequential with respect to previous
274      * accesses.
275      *   
276      * @param tick New data ready tick.
277      */  
278     void setWhenReady(const Tick tick)
279     {        
280         assert(tick >= _tickInserted);
281         whenReady = tick;
282     }    
```

Also, it needs to set the when the block will becomes ready 
by invoking setWhenReady function. 









## Promote MSHR and service its targets (recvTimingResp)
```cpp
 493 
 494     if (blk && blk->isValid() && pkt->isClean() && !pkt->isInvalidate()) {
 495         // The block was marked not readable while there was a pending
 496         // cache maintenance operation, restore its flag.
 497         blk->setCoherenceBits(CacheBlk::ReadableBit);
 498 
 499         // This was a cache clean operation (without invalidate)
 500         // and we have a copy of the block already. Since there
 501         // is no invalidation, we can promote targets that don't
 502         // require a writable copy
 503         mshr->promoteReadable();
 504     }
 505 
 506     if (blk && blk->isSet(CacheBlk::WritableBit) &&
 507         !pkt->req->isCacheInvalidate()) {
 508         // If at this point the referenced block is writable and the
 509         // response is not a cache invalidate, we promote targets that
 510         // were deferred as we couldn't guarrantee a writable copy
 511         mshr->promoteWritable();
 512     }
```


## serviceMSHRTargets (recvTimingResp)
```cpp
 514     serviceMSHRTargets(mshr, pkt, blk);
```
Although it has updated the cache block, still the targets of the MSHR entries 
are waiting the data block is coming to the cache.
The main job of the serviceMSHRTargets function is looping 
targets of the MSHR entries associates with currently received response packet. 
Because there are three different sources for the targets, 
it should be handled differently. 

```cpp
 683 void
 684 Cache::serviceMSHRTargets(MSHR *mshr, const PacketPtr pkt, CacheBlk *blk)
 685 {
 686     QueueEntry::Target *initial_tgt = mshr->getTarget();
 687     // First offset for critical word first calculations
 688     const int initial_offset = initial_tgt->pkt->getOffset(blkSize);
 689 
 690     const bool is_error = pkt->isError();
 691     // allow invalidation responses originating from write-line
 692     // requests to be discarded
 693     bool is_invalidate = pkt->isInvalidate() &&
 694         !mshr->wasWholeLineWrite;
 695 
 696     MSHR::TargetList targets = mshr->extractServiceableTargets(pkt);
 697     for (auto &target: targets) {
 698         Packet *tgt_pkt = target.pkt;
 699         switch (target.source) {
 700           case MSHR::Target::FromCPU:
 701             Tick completion_time;
 702             // Here we charge on completion_time the delay of the xbar if the
 703             // packet comes from it, charged on headerDelay.
 704             completion_time = pkt->headerDelay;
 705 
 706             // Software prefetch handling for cache closest to core
 707             if (tgt_pkt->cmd.isSWPrefetch()) {
 708                 if (tgt_pkt->needsWritable()) {
 709                     // All other copies of the block were invalidated and we
 710                     // have an exclusive copy.
 711 
 712                     // The coherence protocol assumes that if we fetched an
 713                     // exclusive copy of the block, we have the intention to
 714                     // modify it. Therefore the MSHR for the PrefetchExReq has
 715                     // been the point of ordering and this cache has commited
 716                     // to respond to snoops for the block.
 717                     //
 718                     // In most cases this is true anyway - a PrefetchExReq
 719                     // will be followed by a WriteReq. However, if that
 720                     // doesn't happen, the block is not marked as dirty and
 721                     // the cache doesn't respond to snoops that has committed
 722                     // to do so.
 723                     //
 724                     // To avoid deadlocks in cases where there is a snoop
 725                     // between the PrefetchExReq and the expected WriteReq, we
 726                     // proactively mark the block as Dirty.
 727                     assert(blk);
 728                     blk->setCoherenceBits(CacheBlk::DirtyBit);
 729 
 730                     panic_if(isReadOnly, "Prefetch exclusive requests from "
 731                             "read-only cache %s\n", name());
 732                 }
 733 
 734                 // a software prefetch would have already been ack'd
 735                 // immediately with dummy data so the core would be able to
 736                 // retire it. This request completes right here, so we
 737                 // deallocate it.
 738                 delete tgt_pkt;
 739                 break; // skip response
 740             }
 741 
 742             // unlike the other packet flows, where data is found in other
 743             // caches or memory and brought back, write-line requests always
 744             // have the data right away, so the above check for "is fill?"
 745             // cannot actually be determined until examining the stored MSHR
 746             // state. We "catch up" with that logic here, which is duplicated
 747             // from above.
 748             if (tgt_pkt->cmd == MemCmd::WriteLineReq) {
 749                 assert(!is_error);
 750                 assert(blk);
 751                 assert(blk->isSet(CacheBlk::WritableBit));
 752             }
 753 
 754             // Here we decide whether we will satisfy the target using
 755             // data from the block or from the response. We use the
 756             // block data to satisfy the request when the block is
 757             // present and valid and in addition the response in not
 758             // forwarding data to the cache above (we didn't fill
 759             // either); otherwise we use the packet data.
 760             if (blk && blk->isValid() &&
 761                 (!mshr->isForward || !pkt->hasData())) {
 762                 satisfyRequest(tgt_pkt, blk, true, mshr->hasPostDowngrade());
 763 
 764                 // How many bytes past the first request is this one
 765                 int transfer_offset =
 766                     tgt_pkt->getOffset(blkSize) - initial_offset;
 767                 if (transfer_offset < 0) {
 768                     transfer_offset += blkSize;
 769                 }
 770 
 771                 // If not critical word (offset) return payloadDelay.
 772                 // responseLatency is the latency of the return path
 773                 // from lower level caches/memory to an upper level cache or
 774                 // the core.
 775                 completion_time += clockEdge(responseLatency) +
 776                     (transfer_offset ? pkt->payloadDelay : 0);
 777 
 778                 assert(!tgt_pkt->req->isUncacheable());
 779 
 780                 assert(tgt_pkt->req->requestorId() < system->maxRequestors());
 781                 stats.cmdStats(tgt_pkt)
 782                     .missLatency[tgt_pkt->req->requestorId()] +=
 783                     completion_time - target.recvTime;
 784             } else if (pkt->cmd == MemCmd::UpgradeFailResp) {
 785                 // failed StoreCond upgrade
 786                 assert(tgt_pkt->cmd == MemCmd::StoreCondReq ||
 787                        tgt_pkt->cmd == MemCmd::StoreCondFailReq ||
 788                        tgt_pkt->cmd == MemCmd::SCUpgradeFailReq);
 789                 // responseLatency is the latency of the return path
 790                 // from lower level caches/memory to an upper level cache or
 791                 // the core.
 792                 completion_time += clockEdge(responseLatency) +
 793                     pkt->payloadDelay;
 794                 tgt_pkt->req->setExtraData(0);
 795             } else {
 796                 if (is_invalidate && blk && blk->isValid()) {
 797                     // We are about to send a response to a cache above
 798                     // that asked for an invalidation; we need to
 799                     // invalidate our copy immediately as the most
 800                     // up-to-date copy of the block will now be in the
 801                     // cache above. It will also prevent this cache from
 802                     // responding (if the block was previously dirty) to
 803                     // snoops as they should snoop the caches above where
 804                     // they will get the response from.
 805                     invalidateBlock(blk);
 806                 }
 807                 // not a cache fill, just forwarding response
 808                 // responseLatency is the latency of the return path
 809                 // from lower level cahces/memory to the core.
 810                 completion_time += clockEdge(responseLatency) +
 811                     pkt->payloadDelay;
 812                 if (!is_error) {
 813                     if (pkt->isRead()) {
 814                         // sanity check
 815                         assert(pkt->matchAddr(tgt_pkt));
 816                         assert(pkt->getSize() >= tgt_pkt->getSize());
 817 
 818                         tgt_pkt->setData(pkt->getConstPtr<uint8_t>());
 819                     } else {
 820                         // MSHR targets can read data either from the
 821                         // block or the response pkt. If we can't get data
 822                         // from the block (i.e., invalid or has old data)
 823                         // or the response (did not bring in any data)
 824                         // then make sure that the target didn't expect
 825                         // any.
 826                         assert(!tgt_pkt->hasRespData());
 827                     }
 828                 }
 829 
 830                 // this response did not allocate here and therefore
 831                 // it was not consumed, make sure that any flags are
 832                 // carried over to cache above
 833                 tgt_pkt->copyResponderFlags(pkt);
 834             }
 835             tgt_pkt->makeTimingResponse();
 836             // if this packet is an error copy that to the new packet
 837             if (is_error)
 838                 tgt_pkt->copyError(pkt);
 839             if (tgt_pkt->cmd == MemCmd::ReadResp &&
 840                 (is_invalidate || mshr->hasPostInvalidate())) {
 841                 // If intermediate cache got ReadRespWithInvalidate,
 842                 // propagate that.  Response should not have
 843                 // isInvalidate() set otherwise.
 844                 tgt_pkt->cmd = MemCmd::ReadRespWithInvalidate;
 845                 DPRINTF(Cache, "%s: updated cmd to %s\n", __func__,
 846                         tgt_pkt->print());
 847             }
 848             // Reset the bus additional time as it is now accounted for
 849             tgt_pkt->headerDelay = tgt_pkt->payloadDelay = 0;
 850             cpuSidePort.schedTimingResp(tgt_pkt, completion_time);
 851             break;
 ```

For the FromCPU case, there are two main conditions that we need to take care. 
First of all, when the blk associated with current cache block response 
is available, then it will invoke satisfyRequest function. 
However, when the blk points to nullptr, then 
it just copies data from the response packet to the packet 
selected among the targets. 
Regardless of the availability of the blk, 
it invokes schedTimingResp through the cpuSidePort 
to send the response packet to the upper cache or processor. 
Note that this response packet deliver one of targets of the resolved MSHR. 
At the time of exit of the loop, all packers associated with the resolved MSHR entry
will be handled. 

```cpp
 853           case MSHR::Target::FromPrefetcher:
 854             assert(tgt_pkt->cmd == MemCmd::HardPFReq);
 855             if (blk)
 856                 blk->setPrefetched();
 857             delete tgt_pkt;
 858             break;
 859 
 860           case MSHR::Target::FromSnoop:
 861             // I don't believe that a snoop can be in an error state
 862             assert(!is_error);
 863             // response to snoop request
 864             DPRINTF(Cache, "processing deferred snoop...\n");
 865             // If the response is invalidating, a snooping target can
 866             // be satisfied if it is also invalidating. If the reponse is, not
 867             // only invalidating, but more specifically an InvalidateResp and
 868             // the MSHR was created due to an InvalidateReq then a cache above
 869             // is waiting to satisfy a WriteLineReq. In this case even an
 870             // non-invalidating snoop is added as a target here since this is
 871             // the ordering point. When the InvalidateResp reaches this cache,
 872             // the snooping target will snoop further the cache above with the
 873             // WriteLineReq.
 874             assert(!is_invalidate || pkt->cmd == MemCmd::InvalidateResp ||
 875                    pkt->req->isCacheMaintenance() ||
 876                    mshr->hasPostInvalidate());
 877             handleSnoop(tgt_pkt, blk, true, true, mshr->hasPostInvalidate());
 878             break;
 879 
 880           default:
 881             panic("Illegal target->source enum %d\n", target.source);
 882         }
 883     }
 884 
 885     maintainClusivity(targets.hasFromCache, blk);
 886 
 887     if (blk && blk->isValid()) {
 888         // an invalidate response stemming from a write line request
 889         // should not invalidate the block, so check if the
 890         // invalidation should be discarded
 891         if (is_invalidate || mshr->hasPostInvalidate()) {
 892             invalidateBlock(blk);
 893         } else if (mshr->hasPostDowngrade()) {
 894             blk->clearCoherenceBits(CacheBlk::WritableBit);
 895         }
 896     }
 897 }
```

 
 ## Finishing MSHR resolving (recvTimingResp)
 ```cpp
 516     if (mshr->promoteDeferredTargets()) {
 517         // avoid later read getting stale data while write miss is
 518         // outstanding.. see comment in timingAccess()
 519         if (blk) {
 520             blk->clearCoherenceBits(CacheBlk::ReadableBit);
 521         }
 522         mshrQueue.markPending(mshr);
 523         schedMemSideSendEvent(clockEdge() + pkt->payloadDelay);
 524     } else {
 525         // while we deallocate an mshr from the queue we still have to
 526         // check the isFull condition before and after as we might
 527         // have been using the reserved entries already
 528         const bool was_full = mshrQueue.isFull();
 529         mshrQueue.deallocate(mshr);
 530         if (was_full && !mshrQueue.isFull()) {
 531             clearBlocked(Blocked_NoMSHRs);
 532         }
 533 
 534         // Request the bus for a prefetch if this deallocation freed enough
 535         // MSHRs for a prefetch to take place
 536         if (prefetcher && mshrQueue.canPrefetch() && !isBlocked()) {
 537             Tick next_pf_time = std::max(prefetcher->nextPrefetchReadyTime(),
 538                                          clockEdge());
 539             if (next_pf_time != MaxTick)
 540                 schedMemSideSendEvent(next_pf_time);
 541         }
 542     }
 543 
 544     // if we used temp block, check to see if its valid and then clear it out
 545     if (blk == tempBlock && tempBlock->isValid()) {
 546         evictBlock(blk, writebacks);
 547     }
 548 
 549     const Tick forward_time = clockEdge(forwardLatency) + pkt->headerDelay;
 550     // copy writebacks to write buffer
 551     doWritebacks(writebacks, forward_time);
 552 
 553     DPRINTF(CacheVerbose, "%s: Leaving with %s\n", __func__, pkt->print());
 554     delete pkt;
 555 }
```

After processing all targets of the currently selected MSHR entry, 
we should promote deferred targets or deallocate the MSHR entry.
Although we finish processing the targets of the selected MSHR, 
there could be deferred targets for that MSHR entry.
In that case, those targets should be moved to the MSHR, and 
the selected MSHR should not be freed. 
However, if there is no deferred targets, then the selected MSHR 
can be freed. 
Also, if the cache was blocked because of full of MSHR, 
it clear blocking. Furthermore, if possible, 
it generates prefetch request and send it to the memory. 
After the deallocation, 
the evicted packet should be written backs to the higher level cache 
or the memory. The doWritebacks function handles this write back operations.
Also, when the current block is tempBlock and no cache entry has been allocated
for the current response, it should evict the current block.
\XXX{I don't know why tempBlock need to be evicted here..? Cause it didn't generate new cache block..}


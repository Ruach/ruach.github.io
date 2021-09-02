# Memory read and write of the O3 CPU

## Memory read 
```cpp
621 LSQUnit<Impl>::read(LSQRequest *req, int load_idx)
622 {
623     LQEntry& load_req = loadQueue[load_idx];
624     const DynInstPtr& load_inst = load_req.instruction();
625 
626     load_req.setRequest(req);
627     assert(load_inst);
628 
629     assert(!load_inst->isExecuted());
630 
631     // Make sure this isn't a strictly ordered load
632     // A bit of a hackish way to get strictly ordered accesses to work
633     // only if they're at the head of the LSQ and are ready to commit
634     // (at the head of the ROB too).
635 
636     if (req->mainRequest()->isStrictlyOrdered() &&
637         (load_idx != loadQueue.head() || !load_inst->isAtCommit())) {
638         // Tell IQ/mem dep unit that this instruction will need to be
639         // rescheduled eventually
640         iewStage->rescheduleMemInst(load_inst);
641         load_inst->clearIssued();
642         load_inst->effAddrValid(false);
643         ++lsqRescheduledLoads;
644         DPRINTF(LSQUnit, "Strictly ordered load [sn:%lli] PC %s\n",
645                 load_inst->seqNum, load_inst->pcState());
646 
647         // Must delete request now that it wasn't handed off to
648         // memory.  This is quite ugly.  @todo: Figure out the proper
649         // place to really handle request deletes.
650         load_req.setRequest(nullptr);
651         req->discard();
652         return std::make_shared<GenericISA::M5PanicFault>(
653             "Strictly ordered load [sn:%llx] PC %s\n",
654             load_inst->seqNum, load_inst->pcState());
655     }
656 
657     DPRINTF(LSQUnit, "Read called, load idx: %i, store idx: %i, "
658             "storeHead: %i addr: %#x%s\n",
659             load_idx - 1, load_inst->sqIt._idx, storeQueue.head() - 1,
660             req->mainRequest()->getPaddr(), req->isSplit() ? " split" : "");
661 
662     if (req->mainRequest()->isLLSC()) {
663         // Disable recording the result temporarily.  Writing to misc
664         // regs normally updates the result, but this is not the
665         // desired behavior when handling store conditionals.
666         load_inst->recordResult(false);
667         TheISA::handleLockedRead(load_inst.get(), req->mainRequest());
668         load_inst->recordResult(true);
669     }
670 
671     if (req->mainRequest()->isMmappedIpr()) {
672         assert(!load_inst->memData);
673         load_inst->memData = new uint8_t[MaxDataBytes];
674 
675         ThreadContext *thread = cpu->tcBase(lsqID);
676         PacketPtr main_pkt = new Packet(req->mainRequest(), MemCmd::ReadReq);
677 
678         main_pkt->dataStatic(load_inst->memData);
679 
680         Cycles delay = req->handleIprRead(thread, main_pkt);
681 
682         WritebackEvent *wb = new WritebackEvent(load_inst, main_pkt, this);
683         cpu->schedule(wb, cpu->clockEdge(delay));
684         return NoFault;
685     }
686 
687     // Check the SQ for any previous stores that might lead to forwarding
......
840     // If there's no forwarding case, then go access memory
841     DPRINTF(LSQUnit, "Doing memory access for inst [sn:%lli] PC %s\n",
842             load_inst->seqNum, load_inst->pcState());
843 
844     // Allocate memory if this is the first time a load is issued.
845     if (!load_inst->memData) {
846         load_inst->memData = new uint8_t[req->mainRequest()->getSize()];
847     }
848 
849     // For now, load throughput is constrained by the number of
850     // load FUs only, and loads do not consume a cache port (only
851     // stores do).
852     // @todo We should account for cache port contention
853     // and arbitrate between loads and stores.
854 
855     // if we the cache is not blocked, do cache access
856     if (req->senderState() == nullptr) {
857         LQSenderState *state = new LQSenderState(
858                 loadQueue.getIterator(load_idx));
859         state->isLoad = true;
860         state->inst = load_inst;
861         state->isSplit = req->isSplit();
862         req->senderState(state);
863     }
864     req->buildPackets();
865     req->sendPacketToCache();
866     if (!req->isSent())
867         iewStage->blockMemInst(load_inst);
868 
869     return NoFault;
870 }
```

If the current instruction has not initiated the memory load operation before,
then it allocates a memory and make the memData of the instruction 
points to this allocated memory to store the actual data read from cache or memory.
After that, it generates senderState object if it doesn't have.
The state object contains information such as 
whether this request is load or store, 
the instruction that initiated the memory operation, and 
information about whether the request is a split or single access. 
After the senderState is generated, it is stored in the request object.
Note that here the req is the object of LSQRequest.
Remember that the req is the same object used for the TLB resolution.
Because this object contains all information required for resolving one memory operation
including TLB, cache ports, etc, by invoking proper function,
CPU can handle read/write operations. 

### Build packet
```cpp
1032 template<class Impl>
1033 void
1034 LSQ<Impl>::SingleDataRequest::buildPackets()
1035 {  
1036     assert(_senderState);
1037     /* Retries do not create new packets. */
1038     if (_packets.size() == 0) {
1039         _packets.push_back(
1040                 isLoad()
1041                     ?  Packet::createRead(request())
1042                     :  Packet::createWrite(request()));
1043         _packets.back()->dataStatic(_inst->memData);
1044         _packets.back()->senderState = _senderState;
1045     }
1046     assert(_packets.size() == 1);
1047 }
```
```cpp
 276 /**
 277  * A Packet is used to encapsulate a transfer between two objects in
 278  * the memory system (e.g., the L1 and L2 cache).  (In contrast, a
 279  * single Request travels all the way from the requestor to the
 280  * ultimate destination and back, possibly being conveyed by several
 281  * different Packets along the way.)
 282  */
 283 class Packet : public Printable
 284 {
 285   public:
 286     typedef uint32_t FlagsType;
 287     typedef gem5::Flags<FlagsType> Flags;
......
 368   private:
 369    /**
 370     * A pointer to the data being transferred. It can be different
 371     * sizes at each level of the hierarchy so it belongs to the
 372     * packet, not request. This may or may not be populated when a
 373     * responder receives the packet. If not populated memory should
 374     * be allocated.
 375     */
 376     PacketDataPtr data;
......
 846     /**
 847      * Constructor. Note that a Request object must be constructed
 848      * first, but the Requests's physical address and size fields need
 849      * not be valid. The command must be supplied.
 850      */
 851     Packet(const RequestPtr &_req, MemCmd _cmd)
 852         :  cmd(_cmd), id((PacketId)_req.get()), req(_req),
 853            data(nullptr), addr(0), _isSecure(false), size(0),
 854            _qosValue(0),
 855            htmReturnReason(HtmCacheFailure::NO_FAIL),
 856            htmTransactionUid(0),
 857            headerDelay(0), snoopDelay(0),
 858            payloadDelay(0), senderState(NULL)
 859     {
 860         flags.clear();
 861         if (req->hasPaddr()) {
 862             addr = req->getPaddr();
 863             flags.set(VALID_ADDR);
 864             _isSecure = req->isSecure();
 865         }
 866 
 867         /**
 868          * hardware transactional memory
 869          *
 870          * This is a bit of a hack!
 871          * Technically the address of a HTM command is set to zero
 872          * but is not valid. The reason that we pretend it's valid is
 873          * to void the getAddr() function from failing. It would be
 874          * cumbersome to add control flow in many places to check if the
 875          * packet represents a HTM command before calling getAddr().
 876          */
 877         if (req->isHTMCmd()) {
 878             flags.set(VALID_ADDR);
 879             assert(addr == 0x0);
 880         }
 881         if (req->hasSize()) {
 882             size = req->getSize();
 883             flags.set(VALID_SIZE);
 884         }
 885     }
......
1002     /**
1003      * Constructor-like methods that return Packets based on Request objects.
1004      * Fine-tune the MemCmd type if it's not a vanilla read or write.
1005      */
1006     static PacketPtr
1007     createRead(const RequestPtr &req)
1008     {
1009         return new Packet(req, makeReadCmd(req));
1010     }
1011 
1012     static PacketPtr
1013     createWrite(const RequestPtr &req)
1014     {
1015         return new Packet(req, makeWriteCmd(req));
1016     }
```

buildPackets function generates new packet that will be sent to the cache.
The generated packet is maintained in the internal vector called _packets. 
Also, it sets the buffer allocated for storing the data, _inst->memData to 
internal data member field of the packet. Also, the senderState is stored.

```cpp
 386     /**
 387      * A virtual base opaque structure used to hold state associated
 388      * with the packet (e.g., an MSHR), specific to a SimObject that
 389      * sees the packet. A pointer to this state is returned in the
 390      * packet's response so that the SimObject in question can quickly
 391      * look up the state needed to process it. A specific subclass
 392      * would be derived from this to carry state specific to a
 393      * particular sending device.
 394      *
 395      * As multiple SimObjects may add their SenderState throughout the
 396      * memory system, the SenderStates create a stack, where a
 397      * SimObject can add a new Senderstate, as long as the
 398      * predecessing SenderState is restored when the response comes
 399      * back. For this reason, the predecessor should always be
 400      * populated with the current SenderState of a packet before
 401      * modifying the senderState field in the request packet.
 402      */
 403     struct SenderState
 404     {
 405         SenderState* predecessor;
 406         SenderState() : predecessor(NULL) {}
 407         virtual ~SenderState() {}
 408     };
```

### attribute of the packet 
*mem/packet.hh*
```cpp
 209     bool
 210     testCmdAttrib(MemCmd::Attribute attrib) const
 211     {
 212         return commandInfo[cmd].attributes[attrib] != 0;
 213     }
 214 
 215   public:
 216 
 217     bool isRead() const            { return testCmdAttrib(IsRead); }
 218     bool isWrite() const           { return testCmdAttrib(IsWrite); }
 219     bool isUpgrade() const         { return testCmdAttrib(IsUpgrade); }
 220     bool isRequest() const         { return testCmdAttrib(IsRequest); }
 221     bool isResponse() const        { return testCmdAttrib(IsResponse); }
 222     bool needsWritable() const     { return testCmdAttrib(NeedsWritable); }
 223     bool needsResponse() const     { return testCmdAttrib(NeedsResponse); }
 224     bool isInvalidate() const      { return testCmdAttrib(IsInvalidate); }
 225     bool isEviction() const        { return testCmdAttrib(IsEviction); }
 226     bool isClean() const           { return testCmdAttrib(IsClean); }
 227     bool fromCache() const         { return testCmdAttrib(FromCache); }
 ```

*mem/packet.cc*
```cpp
 64 const MemCmd::CommandInfo
 65 MemCmd::commandInfo[] =
 66 {
 67     /* InvalidCmd */
 68     { {}, InvalidCmd, "InvalidCmd" },
 69     /* ReadReq - Read issued by a non-caching agent such as a CPU or
 70      * device, with no restrictions on alignment. */
 71     { {IsRead, IsRequest, NeedsResponse}, ReadResp, "ReadReq" },
 72     /* ReadResp */
 73     { {IsRead, IsResponse, HasData}, InvalidCmd, "ReadResp" },
 74     /* ReadRespWithInvalidate */
 75     { {IsRead, IsResponse, HasData, IsInvalidate},
 76             InvalidCmd, "ReadRespWithInvalidate" },
 77     /* WriteReq */
 78     { {IsWrite, NeedsWritable, IsRequest, NeedsResponse, HasData},
 79             WriteResp, "WriteReq" },
 80     /* WriteResp */
 81     { {IsWrite, IsResponse}, InvalidCmd, "WriteResp" },
 82     /* WriteCompleteResp - The WriteCompleteResp command is needed
 83      * because in the GPU memory model we use a WriteResp to indicate
 84      * that a write has reached the cache controller so we can free
 85      * resources at the coalescer. Later, when the write succesfully
 86      * completes we send a WriteCompleteResp to the CU so its wait
 87      * counters can be updated. Wait counters in the CU is how memory
 88      * dependences are handled in the GPU ISA. */
 89     { {IsWrite, IsResponse}, InvalidCmd, "WriteCompleteResp" },


```



### send packet to the cache
```cpp
1083 template<class Impl>
1084 void
1085 LSQ<Impl>::SingleDataRequest::sendPacketToCache()
1086 {  
1087     assert(_numOutstandingPackets == 0);
1088     if (lsqUnit()->trySendPacket(isLoad(), _packets.at(0)))
1089         _numOutstandingPackets = 1;
1090 }  
```

```cpp
1083 template <class Impl>
1084 bool
1085 LSQUnit<Impl>::trySendPacket(bool isLoad, PacketPtr data_pkt)
1086 {  
1087     bool ret = true;
1088     bool cache_got_blocked = false;
1089         
1090     auto state = dynamic_cast<LSQSenderState*>(data_pkt->senderState);
1091                 
1092     if (!lsq->cacheBlocked() &&
1093         lsq->cachePortAvailable(isLoad)) {
1094         if (!dcachePort->sendTimingReq(data_pkt)) {
1095             ret = false;
1096             cache_got_blocked = true;
1097         } 
1098     } else {
1099         ret = false;
1100     }   
1101     
1102     if (ret) {
1103         if (!isLoad) {
1104             isStoreBlocked = false;
1105         }
1106         lsq->cachePortBusy(isLoad);
1107         state->outstanding++;                
1108         state->request()->packetSent();
1109     } else {
1110         if (cache_got_blocked) {
1111             lsq->cacheBlocked(true);
1112             ++lsqCacheBlocked;
1113         }
1114         if (!isLoad) {
1115             assert(state->request() == storeWBIt->request());
1116             isStoreBlocked = true;
1117         }
1118         state->request()->packetNotSent();
1119     }
1120     return ret;
1121 }
```
This packet will be sent to the cache through the cache port 
connected to the LSQ. 
It first checks whether the cache is currently blocked.
If it is not blocked and there are available read port for the cache,
then it sends the request packet through the dcachePort. 
It can initiate memory access by sending request packet 
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

The sendTimingReq function is very simple. 
Just invoke the recvTimingReq function of the peer connected to the dcachePort
as a slave. 
Because the cache unit is connected to the dcachePort on the other side of the CPU,
we will take a look at the recvTimingReq implementation of the cache unit.


### recvTimingReq of the cache
```cpp
2448 bool
2449 BaseCache::CpuSidePort::recvTimingReq(PacketPtr pkt)
2450 {
2451     assert(pkt->isRequest());
2452 
2453     if (cache->system->bypassCaches()) {
2454         // Just forward the packet if caches are disabled.
2455         // @todo This should really enqueue the packet rather
2456         GEM5_VAR_USED bool success = cache->memSidePort.sendTimingReq(pkt);
2457         assert(success);
2458         return true;
2459     } else if (tryTiming(pkt)) {
2460         cache->recvTimingReq(pkt);
2461         return true;
2462     }
2463     return false;
2464 }
```


```cpp
 349 void
 350 BaseCache::recvTimingReq(PacketPtr pkt)
 351 {   
 352     // anything that is merely forwarded pays for the forward latency and
 353     // the delay provided by the crossbar
 354     Tick forward_time = clockEdge(forwardLatency) + pkt->headerDelay;
 355     
 356     Cycles lat;
 357     CacheBlk *blk = nullptr;
 358     bool satisfied = false;
 359     {   
 360         PacketList writebacks;
 361         // Note that lat is passed by reference here. The function
 362         // access() will set the lat value.
 363         satisfied = access(pkt, blk, lat, writebacks);
 364         
 365         // After the evicted blocks are selected, they must be forwarded
 366         // to the write buffer to ensure they logically precede anything
 367         // happening below
 368         doWritebacks(writebacks, clockEdge(lat + forwardLatency));
 369     }
 370     
......
```




### accessBlock: check if the cache block exist

```cpp
117     /**
118      * Access block and update replacement data. May not succeed, in which case
119      * nullptr is returned. This has all the implications of a cache access and
120      * should only be used as such. Returns the tag lookup latency as a side
121      * effect.
122      *
123      * @param pkt The packet holding the address to find.
124      * @param lat The latency of the tag lookup.
125      * @return Pointer to the cache block if found.
126      */
127     CacheBlk* accessBlock(const PacketPtr pkt, Cycles &lat) override
128     {
129         CacheBlk *blk = findBlock(pkt->getAddr(), pkt->isSecure());
130 
131         // Access all tags in parallel, hence one in each way.  The data side
132         // either accesses all blocks in parallel, or one block sequentially on
133         // a hit.  Sequential access with a miss doesn't access data.
134         stats.tagAccesses += allocAssoc;
135         if (sequentialAccess) {
136             if (blk != nullptr) {
137                 stats.dataAccesses += 1;
138             }
139         } else {
140             stats.dataAccesses += allocAssoc;
141         }
142 
143         // If a cache hit
144         if (blk != nullptr) {
145             // Update number of references to accessed block
146             blk->increaseRefCount();
147 
148             // Update replacement data of accessed block
149             replacementPolicy->touch(blk->replacementData, pkt);
150         }
151 
152         // The tag lookup latency is the same for a hit or a miss
153         lat = lookupLatency;
154 
155         return blk;
156     }
```

```cpp
 79 CacheBlk*
 80 BaseTags::findBlock(Addr addr, bool is_secure) const
 81 {
 82     // Extract block tag
 83     Addr tag = extractTag(addr);
 84 
 85     // Find possible entries that may contain the given address
 86     const std::vector<ReplaceableEntry*> entries =
 87         indexingPolicy->getPossibleEntries(addr);
 88 
 89     // Search for block
 90     for (const auto& location : entries) {
 91         CacheBlk* blk = static_cast<CacheBlk*>(location);
 92         if (blk->matchTag(tag, is_secure)) {
 93             return blk;
 94         }
 95     }
 96 
 97     // Did not find block
 98     return nullptr;
 99 }
```





### allocateBlock
```cpp
1529 CacheBlk*
1530 BaseCache::allocateBlock(const PacketPtr pkt, PacketList &writebacks)
1531 {  
1532     // Get address
1533     const Addr addr = pkt->getAddr();
1534 
1535     // Get secure bit
1536     const bool is_secure = pkt->isSecure();
1537 
1538     // Block size and compression related access latency. Only relevant if
1539     // using a compressor, otherwise there is no extra delay, and the block
1540     // is fully sized
1541     std::size_t blk_size_bits = blkSize*8;
1542     Cycles compression_lat = Cycles(0);
1543     Cycles decompression_lat = Cycles(0);
1544 
1545     // If a compressor is being used, it is called to compress data before
1546     // insertion. Although in Gem5 the data is stored uncompressed, even if a
1547     // compressor is used, the compression/decompression methods are called to
1548     // calculate the amount of extra cycles needed to read or write compressed
1549     // blocks.
1550     if (compressor && pkt->hasData()) {
1551         const auto comp_data = compressor->compress(
1552             pkt->getConstPtr<uint64_t>(), compression_lat, decompression_lat);
1553         blk_size_bits = comp_data->getSizeBits();
1554     }
1555 
1556     // Find replacement victim
1557     std::vector<CacheBlk*> evict_blks;
1558     CacheBlk *victim = tags->findVictim(addr, is_secure, blk_size_bits,
1559                                         evict_blks);
1560    
1561     // It is valid to return nullptr if there is no victim
1562     if (!victim)
1563         return nullptr;
1564 
1565     // Print victim block's information
1566     DPRINTF(CacheRepl, "Replacement victim: %s\n", victim->print());
1567 
1568     // Try to evict blocks; if it fails, give up on allocation
1569     if (!handleEvictions(evict_blks, writebacks)) {
1570         return nullptr;
1571     }
1572 
1573     // Insert new block at victimized entry
1574     tags->insertBlock(pkt, victim);
1575 
1576     // If using a compressor, set compression data. This must be done after
1577     // insertion, as the compression bit may be set.
1578     if (compressor) {
1579         compressor->setSizeBits(victim, blk_size_bits);
1580         compressor->setDecompressionLatency(victim, decompression_lat);
1581     }
1582 
1583     return victim;
1584 }
```


```cpp
158     /**
159      * Find replacement victim based on address. The list of evicted blocks
160      * only contains the victim.
161      *
162      * @param addr Address to find a victim for.
163      * @param is_secure True if the target memory space is secure.
164      * @param size Size, in bits, of new block to allocate.
165      * @param evict_blks Cache blocks to be evicted.
166      * @return Cache block to be replaced.
167      */
168     CacheBlk* findVictim(Addr addr, const bool is_secure,
169                          const std::size_t size,
170                          std::vector<CacheBlk*>& evict_blks) override
171     {
172         // Get possible entries to be victimized
173         const std::vector<ReplaceableEntry*> entries =
174             indexingPolicy->getPossibleEntries(addr);
175 
176         // Choose replacement victim from replacement candidates
177         CacheBlk* victim = static_cast<CacheBlk*>(replacementPolicy->getVictim(
178                                 entries));
179 
180         // There is only one eviction for this replacement
181         evict_blks.push_back(victim);
182 
183         return victim;
184     }
```

getPossibleEntries select entries of one set 
associated with the address passed to the findVictim function.
Because it returns N-ways of entries mapped to one set, 
the getVictim function should search proper entry to evict.
As a result, one entry will be selected and pushed into the eviction list.
For further memory allocation, the invalidated block is returned. 


```cpp
 864 bool
 865 BaseCache::handleEvictions(std::vector<CacheBlk*> &evict_blks,
 866     PacketList &writebacks)
 867 {
 868     bool replacement = false;
 869     for (const auto& blk : evict_blks) {
 870         if (blk->isValid()) {
 871             replacement = true;
 872 
 873             const MSHR* mshr =
 874                 mshrQueue.findMatch(regenerateBlkAddr(blk), blk->isSecure());
 875             if (mshr) {
 876                 // Must be an outstanding upgrade or clean request on a block
 877                 // we're about to replace
 878                 assert((!blk->isSet(CacheBlk::WritableBit) &&
 879                     mshr->needsWritable()) || mshr->isCleaning());
 880                 return false;
 881             }
 882         }
 883     }
 884 
 885     // The victim will be replaced by a new entry, so increase the replacement
 886     // counter if a valid block is being replaced
 887     if (replacement) {
 888         stats.replacements++;
 889 
 890         // Evict valid blocks associated to this victim block
 891         for (auto& blk : evict_blks) {
 892             if (blk->isValid()) {
 893                 evictBlock(blk, writebacks);
 894             }
 895         }
 896     }
 897 
 898     return true;
 899 }
```

```cpp
1606 void
1607 BaseCache::evictBlock(CacheBlk *blk, PacketList &writebacks)
1608 {
1609     PacketPtr pkt = evictBlock(blk);
1610     if (pkt) {
1611         writebacks.push_back(pkt);
1612     }
1613 }
```

```cpp
 899 PacketPtr
 900 Cache::evictBlock(CacheBlk *blk)
 901 {
 902     PacketPtr pkt = (blk->isSet(CacheBlk::DirtyBit) || writebackClean) ?
 903         writebackBlk(blk) : cleanEvictBlk(blk);
 904 
 905     invalidateBlock(blk);
 906 
 907     return pkt;
 908 }
```

```cpp
1586 void
1587 BaseCache::invalidateBlock(CacheBlk *blk)
1588 {
1589     // If block is still marked as prefetched, then it hasn't been used
1590     if (blk->wasPrefetched()) {
1591         prefetcher->prefetchUnused();
1592     }
1593 
1594     // Notify that the data contents for this address are no longer present
1595     updateBlockData(blk, nullptr, blk->isValid());
1596 
1597     // If handling a block present in the Tags, let it do its invalidation
1598     // process, which will update stats and invalidate the block itself
1599     if (blk != tempBlock) {
1600         tags->invalidate(blk);
1601     } else {
1602         tempBlock->invalidate();
1603     }
1604 }   

```

*gem5/src/mem/cache/tags/base.cc*
```cpp
249     /**
250      * This function updates the tags when a block is invalidated
251      *
252      * @param blk A valid block to invalidate.
253      */
254     virtual void invalidate(CacheBlk *blk)
255     {
256         assert(blk);
257         assert(blk->isValid());
258 
259         stats.occupancies[blk->getSrcRequestorId()]--;
260         stats.totalRefs += blk->getRefCount();
261         stats.sampledRefs++;
262 
263         blk->invalidate();
264     }
```

*gem5/src/mem/cache_blk.hh*
```cpp
 70 class CacheBlk : public TaggedEntry
 71 {
 72   public:
......
197     /**
198      * Invalidate the block and clear all state.
199      */
200     virtual void invalidate() override
201     {
202         TaggedEntry::invalidate();
203 
204         clearPrefetched();
205         clearCoherenceBits(AllBits);
206 
207         setTaskId(context_switch_task_id::Unknown);
208         setWhenReady(MaxTick);
209         setRefCount(0);
210         setSrcRequestorId(Request::invldRequestorId);
211         lockList.clear();
212     }
```


*gem5/src/mem/tags/tagged_entry*
```cpp
 46 class TaggedEntry : public ReplaceableEntry
 47 {
......
102     /** Invalidate the block. Its contents are no longer valid. */
103     virtual void invalidate()
104     {
105         _valid = false;
106         setTag(MaxAddr);
107         clearSecure();
108     }

```


## Revisiting revTimingReq of the BaseCache to handle cache hit and miss

```cpp
 349 void
 350 BaseCache::recvTimingReq(PacketPtr pkt)
 ......
 371     // Here we charge the headerDelay that takes into account the latencies
 372     // of the bus, if the packet comes from it.
 373     // The latency charged is just the value set by the access() function.
 374     // In case of a hit we are neglecting response latency.
 375     // In case of a miss we are neglecting forward latency.
 376     Tick request_time = clockEdge(lat);
 377     // Here we reset the timing of the packet.
 378     pkt->headerDelay = pkt->payloadDelay = 0;
 379     
 380     if (satisfied) {
 381         // notify before anything else as later handleTimingReqHit might turn
 382         // the packet in a response
 383         ppHit->notify(pkt);
 384         
 385         if (prefetcher && blk && blk->wasPrefetched()) {
 386             DPRINTF(Cache, "Hit on prefetch for addr %#x (%s)\n",
 387                     pkt->getAddr(), pkt->isSecure() ? "s" : "ns");
 388             blk->clearPrefetched();
 389         }
 390         
 391         handleTimingReqHit(pkt, blk, request_time);
 392     } else {
 393         handleTimingReqMiss(pkt, blk, forward_time, request_time);
 394         
 395         ppMiss->notify(pkt);
 396     }
 397     
 398     if (prefetcher) {
 399         // track time of availability of next prefetch, if any
 400         Tick next_pf_time = prefetcher->nextPrefetchReadyTime();
 401         if (next_pf_time != MaxTick) {
 402             schedMemSideSendEvent(next_pf_time);
 403         }
 404     }
 405 }
```
After executing the access function that asks caches 
if the requested data exists in the cache, 
it returns value to indicate whether there was an item in the cache or not.
The satisfied variable contains the return value of the access.
Therefore, based on the satisfied condition,
it should handle cache hit and miss event differently. 

## When the cache hit happens 
```cpp
 223 void
 224 BaseCache::handleTimingReqHit(PacketPtr pkt, CacheBlk *blk, Tick request_time)
 225 {
 226     if (pkt->needsResponse()) {
 227         // These delays should have been consumed by now
 228         assert(pkt->headerDelay == 0);
 229         assert(pkt->payloadDelay == 0);
 230 
 231         pkt->makeTimingResponse();
 232 
 233         // In this case we are considering request_time that takes
 234         // into account the delay of the xbar, if any, and just
 235         // lat, neglecting responseLatency, modelling hit latency
 236         // just as the value of lat overriden by access(), which calls
 237         // the calculateAccessLatency() function.
 238         cpuSidePort.schedTimingResp(pkt, request_time);
 239     } else {
 240         DPRINTF(Cache, "%s satisfied %s, no response needed\n", __func__,
 241                 pkt->print());
 242 
 243         // queue the packet for deletion, as the sending cache is
 244         // still relying on it; if the block is found in access(),
 245         // CleanEvict and Writeback messages will be deleted
 246         // here as well
 247         pendingDelete.reset(pkt);
 248     }
 249 }
```
Based on the request type of the memory operation, it may or may not require response.
Therefore, it first checks whether the packet requires response 
with the needsResponse method. 
When it requires response, it invokes schedTimingResp of the cpuSidePort. 

```cpp
 93     void schedTimingResp(PacketPtr pkt, Tick when)
 94     { respQueue.schedSendTiming(pkt, when); }
```

The schedTimingResp function is defined in the QueuedResponsePort class
which is one of the ancestor class of the CpuSidePort class. 
Also, schedSendTiming is defined as the member function of the RespPacketQueue 
which is the type of the respQueue. 
The PacketQueue class defines the schedSendTiming method, and 
the RespPacketQueue inherits PacketQueue.

```cpp
106 void
107 PacketQueue::schedSendTiming(PacketPtr pkt, Tick when)
108 {
109     DPRINTF(PacketQueue, "%s for %s address %x size %d when %lu ord: %i\n",
110             __func__, pkt->cmdString(), pkt->getAddr(), pkt->getSize(), when,
111             forceOrder);
112 
113     // we can still send a packet before the end of this tick
114     assert(when >= curTick());
115 
116     // express snoops should never be queued
117     assert(!pkt->isExpressSnoop());
118 
119     // add a very basic sanity check on the port to ensure the
120     // invisible buffer is not growing beyond reasonable limits
121     if (!_disableSanityCheck && transmitList.size() > 128) {
122         panic("Packet queue %s has grown beyond 128 packets\n",
123               name());
124     }
125 
126     // we should either have an outstanding retry, or a send event
127     // scheduled, but there is an unfortunate corner case where the
128     // x86 page-table walker and timing CPU send out a new request as
129     // part of the receiving of a response (called by
130     // PacketQueue::sendDeferredPacket), in which we end up calling
131     // ourselves again before we had a chance to update waitingOnRetry
132     // assert(waitingOnRetry || sendEvent.scheduled());
133 
134     // this belongs in the middle somewhere, so search from the end to
135     // order by tick; however, if forceOrder is set, also make sure
136     // not to re-order in front of some existing packet with the same
137     // address
138     auto it = transmitList.end();
139     while (it != transmitList.begin()) {
140         --it;
141         if ((forceOrder && it->pkt->matchAddr(pkt)) || it->tick <= when) {
142             // emplace inserts the element before the position pointed to by
143             // the iterator, so advance it one step
144             transmitList.emplace(++it, when, pkt);
145             return;
146         }
147     }
148     // either the packet list is empty or this has to be inserted
149     // before every other packet
150     transmitList.emplace_front(when, pkt);
151     schedSendEvent(when);
152 }
```

### transmitList maintains all the packets need to be sent to other end of the port
```cpp
 68     /** A deferred packet, buffered to transmit later. */
 69     class DeferredPacket
 70     {
 71       public:
 72         Tick tick;      ///< The tick when the packet is ready to transmit
 73         PacketPtr pkt;  ///< Pointer to the packet to transmit
 74         DeferredPacket(Tick t, PacketPtr p)
 75             : tick(t), pkt(p)
 76         {}
 77     };
 78 
 79     typedef std::list<DeferredPacket> DeferredPacketList;
 80 
 81     /** A list of outgoing packets. */
 82     DeferredPacketList transmitList;
 83 
```
tranmitList contains all the deferrredPackets that are waiting to be sent.
Therefore, it contains the packet itself and when should it be sent.
Note that when which is the Tick is required because GEM5 is emulator not the hardware. 
Anyway the maintained packets will be sent 
when the schedSendEvent fires. 
Note that it is scheduled to be fired at when clock cycle 
through schedSendEvent function.

### schedSendEvent function schedules event to handle the deferred packet 
```cpp
154 void
155 PacketQueue::schedSendEvent(Tick when)
156 {
157     // if we are waiting on a retry just hold off
158     if (waitingOnRetry) {
159         DPRINTF(PacketQueue, "Not scheduling send as waiting for retry\n");
160         assert(!sendEvent.scheduled());
161         return;
162     }
163 
164     if (when != MaxTick) {
165         // we cannot go back in time, and to be consistent we stick to
166         // one tick in the future
167         when = std::max(when, curTick() + 1);
168         // @todo Revisit the +1
169 
170         if (!sendEvent.scheduled()) {
171             em.schedule(&sendEvent, when);
172         } else if (when < sendEvent.when()) {
173             // if the new time is earlier than when the event
174             // currently is scheduled, move it forward
175             em.reschedule(&sendEvent, when);
176         }
177     } else {
178         // we get a MaxTick when there is no more to send, so if we're
179         // draining, we may be done at this point
180         if (drainState() == DrainState::Draining &&
181             transmitList.empty() && !sendEvent.scheduled()) {
182 
183             DPRINTF(Drain, "PacketQueue done draining,"
184                     "processing drain event\n");
185             signalDrainDone();
186         }
187     }
188 }
```

The most important things done by the schedSendEvent is the scheduling event 
to make it fire at the exact time specified by the GEM5 emulator. 
As shown in Line 170-176,
it first checks whether the sendEvent is already scheduled before.
If there is no scheduled event, then it schedule the event with schedule function.
Note that the em member field points to the BaseCache. 
Also, if there is already pre-scheduled event for the sendEvent and 
if the current event should be raised before the pre-scheduled one,
then it reschedule the event. 
BTW, if there were events that should be handled later then newly scheduled event,
how those events can be processed!?
To understand the how the deferred packet will be processed 
and resolve question, let's take a look at the function invoked 
when the scheduled event raises. 

### processSendEvent: event to handle deferred packet processing
```cpp
 50 PacketQueue::PacketQueue(EventManager& _em, const std::string& _label,
 51                          const std::string& _sendEventName,
 52                          bool force_order,
 53                          bool disable_sanity_check)
 54     : em(_em), sendEvent([this]{ processSendEvent(); }, _sendEventName),
 55       _disableSanityCheck(disable_sanity_check),
 56       forceOrder(force_order),
 57       label(_label), waitingOnRetry(false)
 58 {
 59 }
......
220 void 
221 PacketQueue::processSendEvent()
222 {
223     assert(!waitingOnRetry);
224     sendDeferredPacket();
225 }
```
I can easily find that the sendEvent is initialized with processSendEvent
in the constructor of the PacketQueue. 
Therefore, when the sendEvent fires, it invokes the processSendEvent function.
Note that it further invokes sendDeferredPacket function of the PacketQueue. 

### sendDeferredPacket handles deferred packet processing at right time
```cpp
190 void 
191 PacketQueue::sendDeferredPacket()
192 {
193     // sanity checks
194     assert(!waitingOnRetry);
195     assert(deferredPacketReady());
196 
197     DeferredPacket dp = transmitList.front();
198 
199     // take the packet of the list before sending it, as sending of
200     // the packet in some cases causes a new packet to be enqueued
201     // (most notaly when responding to the timing CPU, leading to a 
202     // new request hitting in the L1 icache, leading to a new
203     // response)
204     transmitList.pop_front();
205 
206     // use the appropriate implementation of sendTiming based on the
207     // type of queue
208     waitingOnRetry = !sendTiming(dp.pkt);
209 
210     // if we succeeded and are not waiting for a retry, schedule the
211     // next send 
212     if (!waitingOnRetry) {
213         schedSendEvent(deferredPacketReadyTime());
214     } else {
215         // put the packet back at the front of the list 
216         transmitList.emplace_front(dp);
217     }    
218 }
```
You might remember that the transmitList contains all the packet and when should it be fired.
And because the sendDeferredPacket is the function that process the packet in the transmitList
at the right time specified. 
Therefore, the sendDeferredPacket extracts the packet from the transmitList (line 197-204).
After getting the packet to send, it invokes sendTiming function to actually send the 
packet to the unit that waits for the response. 
However, you can find that sendTiming function is not implemented on the PacketQueue, 
and implemented as a virtual function, which means 
it should invoke its child's sendTiming.
Remind that the schedTimingResp of the cpuSidePort makes us to all the way down to here. 
Also the respQueue used to schedule sendTiming event was the RespPacketQueue object.
And the RespPacketQueue inherits PacketQueue, which means it has the sendTiming function. 

```cpp
275 bool
276 RespPacketQueue::sendTiming(PacketPtr pkt)
277 {
278     return cpuSidePort.sendTimingResp(pkt);
279 }
```

Finally it invokes sendTimingResp function of the cpuSidePort to send packet to the CPU.
Yeah... It is kind of a long detour to get to the sendTimingResp.
The important reason of this complicated process for handling packets is because 
it wants to decouple the CpuSidePort from the managing response packets.
After the cache generates the response packet, 
instead of directly invoking the sendTimingResp function of the cpuSidePort 
it let the PacketQueue handles all relevant operations to manage response packets.
Anyway, after sendTimingResp is invoked, 
it returns the waitingOnRetry which indicates whether 
the CPU is currently not available for receiving the response packet from the cache. 
In that case, the waitingOnRetry field is set and should send the packet once again
when the CPU send the retry message to the cache at some point. 

```cpp
169     /**
170      * Get the next packet ready time.
171      */
172     Tick deferredPacketReadyTime() const
173     { return transmitList.empty() ? MaxTick : transmitList.front().tick; }
```
Now this is the time for answering previous question: after one packet is processed,
if there are remaining packets need to be sent at some later point, what should we do?
Yeah the deferredPacketReadyTime checks the transmitList and returns the tick 
if deferred packet still remains. 
This tick is passed to the schedSendEvent function, and 
will schedule the sendEvent. 
That's it!

### waitingOnRetry 
\TODO{need to explain some particular details regarding waitingOnRetry}



## When the cache doesn't hit 
When the access function cannot return cache block associated with 
current request, it returns false and satisfied condition doesn't met.
Therefore, the handleTimingReqMiss function is executed to fetch 
cache block from the upper level cache or memory. 

```cpp
 323 void
 324 Cache::handleTimingReqMiss(PacketPtr pkt, CacheBlk *blk, Tick forward_time,
 325                            Tick request_time)
 326 {
 327     if (pkt->req->isUncacheable()) {
 328         // ignore any existing MSHR if we are dealing with an
 329         // uncacheable request
 330 
 331         // should have flushed and have no valid block
 332         assert(!blk || !blk->isValid());
 333 
 334         stats.cmdStats(pkt).mshrUncacheable[pkt->req->requestorId()]++;
 335 
 336         if (pkt->isWrite()) {
 337             allocateWriteBuffer(pkt, forward_time);
 338         } else {
 339             assert(pkt->isRead());
 340 
 341             // uncacheable accesses always allocate a new MSHR
 342 
 343             // Here we are using forward_time, modelling the latency of
 344             // a miss (outbound) just as forwardLatency, neglecting the
 345             // lookupLatency component.
 346             allocateMissBuffer(pkt, forward_time);
 347         }
 348 
 349         return;
 350     }
 351 
 352     Addr blk_addr = pkt->getBlockAddr(blkSize);
 353 
 354     MSHR *mshr = mshrQueue.findMatch(blk_addr, pkt->isSecure());
 355 
 356     // Software prefetch handling:
 357     // To keep the core from waiting on data it won't look at
 358     // anyway, send back a response with dummy data. Miss handling
 359     // will continue asynchronously. Unfortunately, the core will
 360     // insist upon freeing original Packet/Request, so we have to
 361     // create a new pair with a different lifecycle. Note that this
 362     // processing happens before any MSHR munging on the behalf of
 363     // this request because this new Request will be the one stored
 364     // into the MSHRs, not the original.
 365     if (pkt->cmd.isSWPrefetch()) {
 366         assert(pkt->needsResponse());
 367         assert(pkt->req->hasPaddr());
 368         assert(!pkt->req->isUncacheable());
 369 
 370         // There's no reason to add a prefetch as an additional target
 371         // to an existing MSHR. If an outstanding request is already
 372         // in progress, there is nothing for the prefetch to do.
 373         // If this is the case, we don't even create a request at all.
 374         PacketPtr pf = nullptr;
 375 
 376         if (!mshr) {
 377             // copy the request and create a new SoftPFReq packet
 378             RequestPtr req = std::make_shared<Request>(pkt->req->getPaddr(),
 379                                                     pkt->req->getSize(),
 380                                                     pkt->req->getFlags(),
 381                                                     pkt->req->requestorId());
 382             pf = new Packet(req, pkt->cmd);
 383             pf->allocate();
 384             assert(pf->matchAddr(pkt));
 385             assert(pf->getSize() == pkt->getSize());
 386         }
 387 
 388         pkt->makeTimingResponse();
 389 
 390         // request_time is used here, taking into account lat and the delay
 391         // charged if the packet comes from the xbar.
 392         cpuSidePort.schedTimingResp(pkt, request_time);
 393 
 394         // If an outstanding request is in progress (we found an
 395         // MSHR) this is set to null
 396         pkt = pf;
 397     }
 398 
 399     BaseCache::handleTimingReqMiss(pkt, mshr, blk, forward_time, request_time);
 400 }
```

When cache miss happens, the first thing to do is searching the MSHR entry.
The findMatch function of the mshrQueue containing all the previous MSHR entries 
will be invoked to search if there is MSHR entry associated with the current request.
After the serching MSHR queue, it can or cannot find the matching entry.
Regardless of the result, 
it invokes the handleTimingReqMiss of the BaseCache to further handles the cache miss.
Briefly speaking, this function handles cache miss differently based on 
whether the MSHR entry exists or not.
Although some additional operations are done if the missed request is prefetch or uncacheable, 
but I will not deal with them currently. 




## BaseCache::handleTimingReqMiss actually process the cache miss 
Because this function is quite long, I will split it in two parts: 
when MSHR exists and when MSHR doesn't existing.

### When MSHR does exist
```cpp
 251 void
 252 BaseCache::handleTimingReqMiss(PacketPtr pkt, MSHR *mshr, CacheBlk *blk,
 253                                Tick forward_time, Tick request_time)
 254 {
 255     if (writeAllocator &&
 256         pkt && pkt->isWrite() && !pkt->req->isUncacheable()) {
 257         writeAllocator->updateMode(pkt->getAddr(), pkt->getSize(),
 258                                    pkt->getBlockAddr(blkSize));
 259     }
 260 
 261     if (mshr) {
 262         /// MSHR hit
 263         /// @note writebacks will be checked in getNextMSHR()
 264         /// for any conflicting requests to the same block
 265         
 266         //@todo remove hw_pf here
 267         
 268         // Coalesce unless it was a software prefetch (see above).
 269         if (pkt) {
 270             assert(!pkt->isWriteback());
 271             // CleanEvicts corresponding to blocks which have
 272             // outstanding requests in MSHRs are simply sunk here
 273             if (pkt->cmd == MemCmd::CleanEvict) {
 274                 pendingDelete.reset(pkt);
 275             } else if (pkt->cmd == MemCmd::WriteClean) {
 276                 // A WriteClean should never coalesce with any
 277                 // outstanding cache maintenance requests.
 278                 
 279                 // We use forward_time here because there is an
 280                 // uncached memory write, forwarded to WriteBuffer.
 281                 allocateWriteBuffer(pkt, forward_time);
 282             } else {
 283                 DPRINTF(Cache, "%s coalescing MSHR for %s\n", __func__,
 284                         pkt->print());
 285                 
 286                 assert(pkt->req->requestorId() < system->maxRequestors());
 287                 stats.cmdStats(pkt).mshrHits[pkt->req->requestorId()]++;
 288                 
 289                 // We use forward_time here because it is the same
 290                 // considering new targets. We have multiple
 291                 // requests for the same address here. It
 292                 // specifies the latency to allocate an internal
 293                 // buffer and to schedule an event to the queued
 294                 // port and also takes into account the additional
 295                 // delay of the xbar.
 296                 mshr->allocateTarget(pkt, forward_time, order++,
 297                                      allocOnFill(pkt->cmd));
 298                 if (mshr->getNumTargets() == numTarget) {
 299                     noTargetMSHR = mshr;
 300                     setBlocked(Blocked_NoTargets);
 301                     // need to be careful with this... if this mshr isn't
 302                     // ready yet (i.e. time > curTick()), we don't want to
 303                     // move it ahead of mshrs that are ready
 304                     // mshrQueue.moveToFront(mshr);
 305                 }
 306             }
 307         }
```

You have to understand that one MSHR entry can tracks multiple 
memory requests associated with the address handled by the particular MSHR entry. 
Therefore, the first job needs to be done is registering the missed request 
to the MSHR entry as its target. 
Based on the type of the memory request,
it might not add the missed request as the targets of the MSHR entry.
However, in most of the cases, when the L1 cache miss happens, 
it will be added to the found MSHR entry by invoking 
allocateTarget function of the MSHR entry.

### allocateTarget associates the missed requests to the found MSHR entry 
```cpp
372 /*          
373  * Adds a target to an MSHR
374  */         
375 void        
376 MSHR::allocateTarget(PacketPtr pkt, Tick whenReady, Counter _order,
377                      bool alloc_on_fill)
378 {           
379     // assume we'd never issue a prefetch when we've got an
380     // outstanding miss
381     assert(pkt->cmd != MemCmd::HardPFReq);
382                 
383     // if there's a request already in service for this MSHR, we will
384     // have to defer the new target until after the response if any of
385     // the following are true:
386     // - there are other targets already deferred
387     // - there's a pending invalidate to be applied after the response
388     //   comes back (but before this target is processed)
389     // - the MSHR's first (and only) non-deferred target is a cache
390     //   maintenance packet
391     // - the new target is a cache maintenance packet (this is probably
392     //   overly conservative but certainly safe)
393     // - this target requires a writable block and either we're not
394     //   getting a writable block back or we have already snooped
395     //   another read request that will downgrade our writable block
396     //   to non-writable (Shared or Owned)
397     PacketPtr tgt_pkt = targets.front().pkt;
398     if (pkt->req->isCacheMaintenance() ||
399         tgt_pkt->req->isCacheMaintenance() ||
400         !deferredTargets.empty() ||
401         (inService &&
402          (hasPostInvalidate() ||
403           (pkt->needsWritable() &&
404            (!isPendingModified() || hasPostDowngrade() || isForward))))) {
405         // need to put on deferred list
406         if (inService && hasPostInvalidate())
407             replaceUpgrade(pkt);
408         deferredTargets.add(pkt, whenReady, _order, Target::FromCPU, true,
409                             alloc_on_fill);
410     } else {
411         // No request outstanding, or still OK to append to
412         // outstanding request: append to regular target list.  Only
413         // mark pending if current request hasn't been issued yet
414         // (isn't in service).
415         targets.add(pkt, whenReady, _order, Target::FromCPU, !inService,
416                     alloc_on_fill);
417     }
418 
419     DPRINTF(MSHR, "After target allocation: %s", print());
420 }
```
The basic functionality of the allocateTarget is adding the missed memory request 
to one particular MSHR entries' target list. 
Because MSHR collects every memory accesses targeting specific address 
and maintains them as its targets, 
this function must associates the missed packet to proper MSHR entry. 
Also, based on the current condition of the MSHR and pending requests associated with that MSHR entry,
the new packet can be added to either deferredTargets and targets.
Because they are all TargetList objects, let's take a look at it first.

### Target and TargetList
The TargetList is the expanded vector class with Target type. 
Because one MSHR should record all the memory request 
associated with that entry, 
the TargetList vector stores all the missed request and associated information together
represented as a Target type. 

```cpp
129     class Target : public QueueEntry::Target
130     {   
131       public:
132         
133         enum Source
134         {
135             FromCPU,
136             FromSnoop,
137             FromPrefetcher
138         };
139 
140         const Source source;  //!< Request from cpu, memory, or prefetcher?
141 
142         /**
143          * We use this flag to track whether we have cleared the
144          * downstreamPending flag for the MSHR of the cache above
145          * where this packet originates from and guard noninitial
146          * attempts to clear it.
147          *
148          * The flag markedPending needs to be updated when the
149          * TargetList is in service which can be:
150          * 1) during the Target instantiation if the MSHR is in
151          * service and the target is not deferred,
152          * 2) when the MSHR becomes in service if the target is not
153          * deferred,
154          * 3) or when the TargetList is promoted (deferredTargets ->
155          * targets).
156          */
157         bool markedPending;
158 
159         const bool allocOnFill;   //!< Should the response servicing this
160                                   //!< target list allocate in the cache?
161 
162         Target(PacketPtr _pkt, Tick _readyTime, Counter _order,
163                Source _source, bool _markedPending, bool alloc_on_fill)
164             : QueueEntry::Target(_pkt, _readyTime, _order), source(_source),
165               markedPending(_markedPending), allocOnFill(alloc_on_fill)
166         {}
167     };
168 
169     class TargetList : public std::list<Target>, public Named
170     {
```


### When no MSHR is present 
```cpp
 308     } else {
 309         // no MSHR
 310         assert(pkt->req->requestorId() < system->maxRequestors());
 311         stats.cmdStats(pkt).mshrMisses[pkt->req->requestorId()]++;
 312         if (prefetcher && pkt->isDemand())
 313             prefetcher->incrDemandMhsrMisses();
 314 
 315         if (pkt->isEviction() || pkt->cmd == MemCmd::WriteClean) {
 316             // We use forward_time here because there is an
 317             // writeback or writeclean, forwarded to WriteBuffer.
 318             allocateWriteBuffer(pkt, forward_time);
 319         } else {
 320             if (blk && blk->isValid()) {
 321                 // If we have a write miss to a valid block, we
 322                 // need to mark the block non-readable.  Otherwise
 323                 // if we allow reads while there's an outstanding
 324                 // write miss, the read could return stale data
 325                 // out of the cache block... a more aggressive
 326                 // system could detect the overlap (if any) and
 327                 // forward data out of the MSHRs, but we don't do
 328                 // that yet.  Note that we do need to leave the
 329                 // block valid so that it stays in the cache, in
 330                 // case we get an upgrade response (and hence no
 331                 // new data) when the write miss completes.
 332                 // As long as CPUs do proper store/load forwarding
 333                 // internally, and have a sufficiently weak memory
 334                 // model, this is probably unnecessary, but at some
 335                 // point it must have seemed like we needed it...
 336                 assert((pkt->needsWritable() &&
 337                     !blk->isSet(CacheBlk::WritableBit)) ||
 338                     pkt->req->isCacheMaintenance());
 339                 blk->clearCoherenceBits(CacheBlk::ReadableBit);
 340             }
 341             // Here we are using forward_time, modelling the latency of
 342             // a miss (outbound) just as forwardLatency, neglecting the
 343             // lookupLatency component.
 344             allocateMissBuffer(pkt, forward_time);
 345         }
 346     }
 347 }
```

```cpp
1164     MSHR *allocateMissBuffer(PacketPtr pkt, Tick time, bool sched_send = true)
1165     {
1166         MSHR *mshr = mshrQueue.allocate(pkt->getBlockAddr(blkSize), blkSize,
1167                                         pkt, time, order++,
1168                                         allocOnFill(pkt->cmd));
1169 
1170         if (mshrQueue.isFull()) {
1171             setBlocked((BlockedCause)MSHRQueue_MSHRs);
1172         }
1173 
1174         if (sched_send) {
1175             // schedule the send
1176             schedMemSideSendEvent(time);
1177         }
1178 
1179         return mshr;
1180     }
```
allocateMissBuffer generates new mshr entry.



### When and Who manages the targets of the MSHR? 
```cpp
 157         /**
 158          * Schedule a send of a request packet (from the MSHR). Note
 159          * that we could already have a retry outstanding.
 160          */
 161         void schedSendEvent(Tick time)
 162         {
 163             DPRINTF(CachePort, "Scheduling send event at %llu\n", time);
 164             reqQueue.schedSendEvent(time);
 165         }
......
1257     /**
1258      * Schedule a send event for the memory-side port. If already
1259      * scheduled, this may reschedule the event at an earlier
1260      * time. When the specified time is reached, the port is free to
1261      * send either a response, a request, or a prefetch request.
1262      *
1263      * @param time The time when to attempt sending a packet.
1264      */
1265     void schedMemSideSendEvent(Tick time)
1266     {
1267         memSidePort.schedSendEvent(time);
1268     }

```











# Two ports in the cache 
```cpp
  92 /**
  93  * A basic cache interface. Implements some common functions for speed.
  94  */
  95 class BaseCache : public ClockedObject
  96 {
......
 338     CpuSidePort cpuSidePort;
 339     MemSidePort memSidePort;
```

## CpuSidePort: receive request from the processor and send response
 ```cpp
 307     /**
 308      * The CPU-side port extends the base cache response port with access
 309      * functions for functional, atomic and timing requests.
 310      */
 311     class CpuSidePort : public CacheResponsePort
 312     {
 313       private:
 314 
 315         // a pointer to our specific cache implementation
 316         BaseCache *cache;
 317 
 318       protected:
 319         virtual bool recvTimingSnoopResp(PacketPtr pkt) override;
 320 
 321         virtual bool tryTiming(PacketPtr pkt) override;
 322 
 323         virtual bool recvTimingReq(PacketPtr pkt) override;
 324 
 325         virtual Tick recvAtomic(PacketPtr pkt) override;
 326 
 327         virtual void recvFunctional(PacketPtr pkt) override;
 328 
 329         virtual AddrRangeList getAddrRanges() const override;
 330 
 331       public:
 332 
 333         CpuSidePort(const std::string &_name, BaseCache *_cache,
 334                     const std::string &_label);
 335 
 336     };
 337 
```
```cpp
  79 BaseCache::BaseCache(const BaseCacheParams &p, unsigned blk_size)
  80     : ClockedObject(p),
  81       cpuSidePort (p.name + ".cpu_side_port", this, "CpuSidePort"),
  82       memSidePort(p.name + ".mem_side_port", this, "MemSidePort"),
  83       mshrQueue("MSHRs", p.mshrs, 0, p.demand_mshr_reserve, p.name),
  84       writeBuffer("write buffer", p.write_buffers, p.mshrs, p.name),
```
cpuSidePort is a member field of the BaseCache, but it has cache member field
which is a pointer to the BaseCache.
Note that this field is initialized as pointing to the BaseCache itself 
that embeds the cpuSidePort.
Also, it has recvTimingReq function that will be invoked 
when the processor tries to send request to the cache. 


### CacheResponsePort
```cpp
 266     /**
 267      * A cache response port is used for the CPU-side port of the cache,
 268      * and it is basically a simple timing port that uses a transmit
 269      * list for responses to the CPU (or connected requestor). In
 270      * addition, it has the functionality to block the port for
 271      * incoming requests. If blocked, the port will issue a retry once
 272      * unblocked.
 273      */
 274     class CacheResponsePort : public QueuedResponsePort
 275     {
 276 
 277       public:
 278 
 279         /** Do not accept any new requests. */
 280         void setBlocked();
 281 
 282         /** Return to normal operation and accept new requests. */
 283         void clearBlocked();
 284 
 285         bool isBlocked() const { return blocked; }
 286 
 287       protected:
 288 
 289         CacheResponsePort(const std::string &_name, BaseCache *_cache,
 290                        const std::string &_label);
 291 
 292         /** A normal packet queue used to store responses. */
 293         RespPacketQueue queue;
 294 
 295         bool blocked;
 296 
 297         bool mustSendRetry;
 298 
 299       private:
 300 
 301         void processSendRetry();
 302 
 303         EventFunctionWrapper sendRetryEvent;
 304 
 305     };
```

```cpp
  69 BaseCache::CacheResponsePort::CacheResponsePort(const std::string &_name,
  70                                           BaseCache *_cache,
  71                                           const std::string &_label)
  72     : QueuedResponsePort(_name, _cache, queue),
  73       queue(*_cache, *this, true, _label),
  74       blocked(false), mustSendRetry(false),
  75       sendRetryEvent([this]{ processSendRetry(); }, _name)
  76 {
  77 }
```

The CpuSidePort class inherits the CacheResponsePort. 
The main functionality of the CacheResponsePort is allowing the port 
to be blocked while it is busy to process previous packets. 

### QueuedResponsePort
```cpp
 53 /**
 54  * A queued port is a port that has an infinite queue for outgoing
 55  * packets and thus decouples the module that wants to send
 56  * request/responses from the flow control (retry mechanism) of the
 57  * port. A queued port can be used by both a requestor and a responder. The
 58  * queue is a parameter to allow tailoring of the queue implementation
 59  * (used in the cache).
 60  */      
 61 class QueuedResponsePort : public ResponsePort
 62 {      
 63 
 64   protected:
 65 
 66     /** Packet queue used to store outgoing responses. */
 67     RespPacketQueue &respQueue;
 68 
 69     void recvRespRetry() { respQueue.retry(); }
 70 
 71   public:
 72 
 73     /**
 74      * Create a QueuedPort with a given name, owner, and a supplied
 75      * implementation of a packet queue. The external definition of
 76      * the queue enables e.g. the cache to implement a specific queue
 77      * behaviuor in a subclass, and provide the latter to the
 78      * QueuePort constructor. 
 79      */
 80     QueuedResponsePort(const std::string& name, SimObject* owner,
 81                     RespPacketQueue &resp_queue, PortID id = InvalidPortID) :
 82         ResponsePort(name, owner, id), respQueue(resp_queue)
 83     { }
 84 
 85     virtual ~QueuedResponsePort() { }
 86 
 87     /**
 88      * Schedule the sending of a timing response.
 89      *
 90      * @param pkt Packet to send
 91      * @param when Absolute time (in ticks) to send packet
 92      */
 93     void schedTimingResp(PacketPtr pkt, Tick when)
 94     { respQueue.schedSendTiming(pkt, when); }
 95 
 96     /** Check the list of buffered packets against the supplied
 97      * functional request. */
 98     bool trySatisfyFunctional(PacketPtr pkt)
 99     { return respQueue.trySatisfyFunctional(pkt); }
100 };
```

### ResponsePort
```cpp
259 /**
260  * A ResponsePort is a specialization of a port. In addition to the
261  * basic functionality of sending packets to its requestor peer, it also
262  * has functions specific to a responder, e.g. to send range changes
263  * and get the address ranges that the port responds to.
264  *
265  * The three protocols are atomic, timing, and functional, each with its own
266  * header file.
267  */
268 class ResponsePort : public Port, public AtomicResponseProtocol,
269     public TimingResponseProtocol, public FunctionalResponseProtocol
270 {
271     friend class RequestPort;
272 
273   private:
274     RequestPort* _requestPort;
275 
276     bool defaultBackdoorWarned;
277 
278   protected:
279     SimObject& owner;
280 
281   public:
282     ResponsePort(const std::string& name, SimObject* _owner,
283               PortID id=InvalidPortID);
284     virtual ~ResponsePort();
285 
286     /**
287      * Find out if the peer request port is snooping or not.
288      *
289      * @return true if the peer request port is snooping
290      */
291     bool isSnooping() const { return _requestPort->isSnooping(); }
292 
293     /**
294      * Called by the owner to send a range change
295      */
296     void sendRangeChange() const { _requestPort->recvRangeChange(); }
297 
298     /**
299      * Get a list of the non-overlapping address ranges the owner is
300      * responsible for. All response ports must override this function
301      * and return a populated list with at least one item.
302      *
303      * @return a list of ranges responded to
304      */
305     virtual AddrRangeList getAddrRanges() const = 0;
306 
307     /**
308      * We let the request port do the work, so these don't do anything.
309      */
310     void unbind() override {}
311     void bind(Port &peer) override {}
312 
313   public:
314     /* The atomic protocol. */
315 
316     /**
317      * Send an atomic snoop request packet, where the data is moved
318      * and the state is updated in zero time, without interleaving
319      * with other memory accesses.
320      *
321      * @param pkt Snoop packet to send.
322      *
323      * @return Estimated latency of access.
324      */
325     Tick
326     sendAtomicSnoop(PacketPtr pkt)
327     {
328         try {
329             return AtomicResponseProtocol::sendSnoop(_requestPort, pkt);
330         } catch (UnboundPortException) {
331             reportUnbound();
332         }
333     }
334 
335   public:
336     /* The functional protocol. */
337 
338     /**
339      * Send a functional snoop request packet, where the data is
340      * instantly updated everywhere in the memory system, without
341      * affecting the current state of any block or moving the block.
342      *
343      * @param pkt Snoop packet to send.
344      */
345     void
346     sendFunctionalSnoop(PacketPtr pkt) const
347     {
348         try {
349             FunctionalResponseProtocol::sendSnoop(_requestPort, pkt);
350         } catch (UnboundPortException) {
351             reportUnbound();
352         }
353     }
354 
355   public:
356     /* The timing protocol. */
357 
358     /**
359      * Attempt to send a timing response to the request port by calling
360      * its corresponding receive function. If the send does not
361      * succeed, as indicated by the return value, then the sender must
362      * wait for a recvRespRetry at which point it can re-issue a
363      * sendTimingResp.
364      *
365      * @param pkt Packet to send.
366      *
367      * @return If the send was successful or not.
368     */
369     bool
370     sendTimingResp(PacketPtr pkt)
371     {
372         try {
373             return TimingResponseProtocol::sendResp(_requestPort, pkt);
374         } catch (UnboundPortException) {
375             reportUnbound();
376         }
377     }
378 
379     /**
380      * Attempt to send a timing snoop request packet to the request port
381      * by calling its corresponding receive function. Snoop requests
382      * always succeed and hence no return value is needed.
383      *
384      * @param pkt Packet to send.
385      */
386     void
387     sendTimingSnoopReq(PacketPtr pkt)
388     {
389         try {
390             TimingResponseProtocol::sendSnoopReq(_requestPort, pkt);
391         } catch (UnboundPortException) {
392             reportUnbound();
393         }
394     }
395 
396     /**
397      * Send a retry to the request port that previously attempted a
398      * sendTimingReq to this response port and failed.
399      */
400     void
401     sendRetryReq()
402     {
403         try {
404             TimingResponseProtocol::sendRetryReq(_requestPort);
405         } catch (UnboundPortException) {
406             reportUnbound();
407         }
408     }
409 
410     /**
411      * Send a retry to the request port that previously attempted a
412      * sendTimingSnoopResp to this response port and failed.
413      */
414     void
415     sendRetrySnoopResp()
416     {
417         try {
418             TimingResponseProtocol::sendRetrySnoopResp(_requestPort);
419         } catch (UnboundPortException) {
420             reportUnbound();
421         }
422     }
423 
424   protected:
425     /**
426      * Called by the request port to unbind. Should never be called
427      * directly.
428      */
429     void responderUnbind();
430 
431     /**
432      * Called by the request port to bind. Should never be called
433      * directly.
434      */
435     void responderBind(RequestPort& request_port);
436 
437     /**
438      * Default implementations.
439      */
440     Tick recvAtomicBackdoor(PacketPtr pkt, MemBackdoorPtr &backdoor) override;
441 
442     bool
443     tryTiming(PacketPtr pkt) override
444     {
445         panic("%s was not expecting a %s\n", name(), __func__);
446     }
447 
448     bool
449     recvTimingSnoopResp(PacketPtr pkt) override
450     {
451         panic("%s was not expecting a timing snoop response\n", name());
452     }
453 };
```
This is the basic class that provides most of the interfaces 
required for handling receive operations.
Although some operations are not provided by the ResponsePort,
but they are provided by the TimingResponseProtocol 
inherited by the ResponsePort.

```cpp
169 /**
170  * Response port
171  */
172 ResponsePort::ResponsePort(const std::string& name, SimObject* _owner,
173     PortID id) : Port(name, id), _requestPort(&defaultRequestPort),
174     defaultBackdoorWarned(false), owner(*_owner)
175 {
176 }
177 
178 ResponsePort::~ResponsePort()
179 {
180 }
181 
182 void
183 ResponsePort::responderUnbind()
184 {
185     _requestPort = &defaultRequestPort;
186     Port::unbind();
187 }
188 
189 void
190 ResponsePort::responderBind(RequestPort& request_port)
191 {
192     _requestPort = &request_port;
193     Port::bind(request_port);
194 }
```
ResponsePort is initialized with defaultRequestPort by default.
Because ResponsePort needs to understand who sent the request (_requestPort),
the RequestPort object reference should be passed to the 
ResponsePort at the time of construction.
Or dynamically, it can bind to another RequestPort through the responderBind method. 
When proper RequestPort is not set for the ResponsePort, 
it will generate error messages during execution of the GEM5. 


## RespPacketQueue
One thing that should be maintained by the QueuedResponsePort is 
the response packets.
When the all cache accesses finished, it should pass the response packet to the processor.
However, when the processor is busy not to get the response from the cache,
then it should retry later.
For that purpose, the QueuedResponsePort contains RespPacketQueue 
which maintains all the unhandled response packets. 


```cpp
300 class RespPacketQueue : public PacketQueue
301 {
302 
303   protected:
304 
305     ResponsePort& cpuSidePort;
306 
307     // Static definition so it can be called when constructing the parent
308     // without us being completely initialized.
309     static const std::string name(const ResponsePort& cpuSidePort,
310                                   const std::string& label)
311     { return cpuSidePort.name() + "-" + label; }
312 
313   public:
314 
315     /**
316      * Create a response packet queue, linked to an event manager, a
317      * CPU-side port, and a label that will be used for functional print
318      * request packets.
319      *
320      * @param _em Event manager used for scheduling this queue
321      * @param _cpu_side_port Cpu_side port used to send the packets
322      * @param force_order Force insertion order for packets with same address
323      * @param _label Label to push on the label stack for print request packets
324      */
325     RespPacketQueue(EventManager& _em, ResponsePort& _cpu_side_port,
326                     bool force_order = false,
327                     const std::string _label = "RespPacketQueue");
328 
329     virtual ~RespPacketQueue() { }
330 
331     const std::string name() const
332     { return name(cpuSidePort, label); }
333 
334     bool sendTiming(PacketPtr pkt);
335 
336 };
```

```cpp
266 RespPacketQueue::RespPacketQueue(EventManager& _em,
267                                  ResponsePort& _cpu_side_port,
268                                  bool force_order,
269                                  const std::string _label)
270     : PacketQueue(_em, _label, name(_cpu_side_port, _label), force_order),
271       cpuSidePort(_cpu_side_port)
272 {
273 }
274 
275 bool
276 RespPacketQueue::sendTiming(PacketPtr pkt)
277 {
278     return cpuSidePort.sendTimingResp(pkt);
279 }
```

RespPacketQueue has cpuSidePort as its member and initialized by its constructor. 
When the sendTiming function of the RespPacketQueue is invoked,
it sends the packet through the cpuSidePort using the sendTimingResp. 
Also, note that the RespPacketQueue is initialized with the EventManager object's reference.
However, when you take a look at its initialization 
in the BaseCache::CacheResponsePort::CacheResponsePort,
the queue which is the RespPacketQueue object is initialized with 
_cache as its first operand. 
Yeah it is not the EventManager but the BaseCache!
Because the BaseCache is SimObject, it must inherit from EventManager class.
Therefore, the cache object itself can be handled as the EventManager object. 
Let's take a look at the PacketQueue which is the parent class of RespPacketQueue.
Also, note that RespPacketQueue itself is not capable of scheduling event
because it doesn't have any member function or field to utilize the 
passed EventManager, BaseCache.

### PacketQueue 
Instead of the RespPacketQueue, its parent class, PacketQueue utilizes the EventManager
and organize events using the schedule method and EventFunctionWrapper. 

```cpp
 61 /**
 62  * A packet queue is a class that holds deferred packets and later
 63  * sends them using the associated CPU-side port or memory-side port.
 64  */
 65 class PacketQueue : public Drainable
 66 {
 67   private:
 68     /** A deferred packet, buffered to transmit later. */
 69     class DeferredPacket
 70     {
 71       public:
 72         Tick tick;      ///< The tick when the packet is ready to transmit
 73         PacketPtr pkt;  ///< Pointer to the packet to transmit
 74         DeferredPacket(Tick t, PacketPtr p)
 75             : tick(t), pkt(p)
 76         {}
 77     };
 78 
 79     typedef std::list<DeferredPacket> DeferredPacketList;
 80 
 81     /** A list of outgoing packets. */
 82     DeferredPacketList transmitList;
 83 
 84     /** The manager which is used for the event queue */
 85     EventManager& em;
 86 
 87     /** Used to schedule sending of deferred packets. */
 88     void processSendEvent();
 89 
 90     /** Event used to call processSendEvent. */
 91     EventFunctionWrapper sendEvent;
 92 
 93      /*
 94       * Optionally disable the sanity check
 95       * on the size of the transmitList. The
 96       * sanity check will be enabled by default.
 97       */
 98     bool _disableSanityCheck;
 99 
100     /**
101      * if true, inserted packets have to be unconditionally scheduled
102      * after the last packet in the queue that references the same
103      * address
104      */
105     bool forceOrder;
106 
107   protected:
108 
109     /** Label to use for print request packets label stack. */
110     const std::string label;
111 
112     /** Remember whether we're awaiting a retry. */
113     bool waitingOnRetry;
114 
115     /** Check whether we have a packet ready to go on the transmit list. */
116     bool deferredPacketReady() const
117     { return !transmitList.empty() && transmitList.front().tick <= curTick(); }
118 
119     /**
120      * Attempt to send a packet. Note that a subclass of the
121      * PacketQueue can override this method and thus change the
122      * behaviour (as done by the cache for the request queue). The
123      * default implementation sends the head of the transmit list. The
124      * caller must guarantee that the list is non-empty and that the
125      * head packet is scheduled for curTick() (or earlier).
126      */
127     virtual void sendDeferredPacket();
128 
129     /**
130      * Send a packet using the appropriate method for the specific
131      * subclass (request, response or snoop response).
132      */
133     virtual bool sendTiming(PacketPtr pkt) = 0;
134 
135     /**
136      * Create a packet queue, linked to an event manager, and a label
137      * that will be used for functional print request packets.
138      *
139      * @param _em Event manager used for scheduling this queue
140      * @param _label Label to push on the label stack for print request packets
141      * @param force_order Force insertion order for packets with same address
142      * @param disable_sanity_check Flag used to disable the sanity check
143      *        on the size of the transmitList. The check is enabled by default.
144      */
145     PacketQueue(EventManager& _em, const std::string& _label,
146                 const std::string& _sendEventName,
147                 bool force_order = false,
148                 bool disable_sanity_check = false);
149 
150     /**
151      * Virtual desctructor since the class may be used as a base class.
152      */
153     virtual ~PacketQueue();
154 
155   public:
156 
157     /**
158      * Provide a name to simplify debugging.
159      *
160      * @return A complete name, appended to module and port
161      */
162     virtual const std::string name() const = 0;
163 
164     /**
165      * Get the size of the queue.
166      */
167     size_t size() const { return transmitList.size(); }
168 
169     /**
170      * Get the next packet ready time.
171      */
172     Tick deferredPacketReadyTime() const
173     { return transmitList.empty() ? MaxTick : transmitList.front().tick; }
174 
175     /**
176      * Check if a packet corresponding to the same address exists in the
177      * queue.
178      *
179      * @param pkt The packet to compare against.
180      * @param blk_size Block size in bytes.
181      * @return Whether a corresponding packet is found.
182      */
183     bool checkConflict(const PacketPtr pkt, const int blk_size) const;
184 
185     /** Check the list of buffered packets against the supplied
186      * functional request. */
187     bool trySatisfyFunctional(PacketPtr pkt);
188 
189     /**
190      * Schedule a send event if we are not already waiting for a
191      * retry. If the requested time is before an already scheduled
192      * send event, the event will be rescheduled. If MaxTick is
193      * passed, no event is scheduled. Instead, if we are idle and
194      * asked to drain then check and signal drained.
195      *
196      * @param when time to schedule an event
197      */
198     void schedSendEvent(Tick when);
199 
200     /**
201      * Add a packet to the transmit list, and schedule a send event.
202      *
203      * @param pkt Packet to send
204      * @param when Absolute time (in ticks) to send packet
205      */
206     void schedSendTiming(PacketPtr pkt, Tick when);
207 
208     /**
209      * Retry sending a packet from the queue. Note that this is not
210      * necessarily the same packet if something has been added with an
211      * earlier time stamp.
212      */
213     void retry();
214 
215     /**
216       * This allows a user to explicitly disable the sanity check
217       * on the size of the transmitList, which is enabled by default.
218       * Users must use this function to explicitly disable the sanity
219       * check.
220       */
221     void disableSanityCheck() { _disableSanityCheck = true; }
222 
223     DrainState drain() override;
224 };
```


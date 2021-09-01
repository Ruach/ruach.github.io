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

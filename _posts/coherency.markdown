### Basic coherency bits
```cpp
 65 /**
 66  * A Basic Cache block.
 67  * Contains information regarding its coherence, prefetching status, as
 68  * well as a pointer to its data.
 69  */
 70 class CacheBlk : public TaggedEntry
 71 {
 72   public:
 73     /**
 74      * Cache block's enum listing the supported coherence bits. The valid
 75      * bit is not defined here because it is part of a TaggedEntry.
 76      */
 77     enum CoherenceBits : unsigned
 78     {
 79         /** write permission */
 80         WritableBit =       0x02,
 81         /**
 82          * Read permission. Note that a block can be valid but not readable
 83          * if there is an outstanding write upgrade miss.
 84          */
 85         ReadableBit =       0x04,
 86         /** dirty (modified) */
 87         DirtyBit =          0x08,
 88 
 89         /**
 90          * Helper enum value that includes all other bits. Whenever a new
 91          * bits is added, this should be updated.
 92          */
 93         AllBits  =          0x0E,
 94     };
```

CacheBlk defines three coherence bits. 
Among the three, writable and dirty bit is important 
to decide the state of the coherency of one cache block.
Also, the valid bit does important rule, but 
it is defined in the TaggedEntry class. 
Based on those three bits, coherency state can be determined
as described in the following code.

### Coherency state determined by three bits
```cpp
363     std::string
364     print() const override
365     {
366         /**
367          *  state       M   O   E   S   I
368          *  writable    1   0   1   0   0
369          *  dirty       1   1   0   0   0
370          *  valid       1   1   1   1   0
371          *
372          *  state   writable    dirty   valid
373          *  M       1           1       1
374          *  O       0           1       1
375          *  E       1           0       1
376          *  S       0           0       1
377          *  I       0           0       0
378          *
379          * Note that only one cache ever has a block in Modified or
380          * Owned state, i.e., only one cache owns the block, or
381          * equivalently has the DirtyBit bit set. However, multiple
382          * caches on the same path to memory can have a block in the
383          * Exclusive state (despite the name). Exclusive means this
384          * cache has the only copy at this level of the hierarchy,
385          * i.e., there may be copies in caches above this cache (in
386          * various states), but there are no peers that have copies on
387          * this branch of the hierarchy, and no caches at or above
388          * this level on any other branch have copies either.
389          **/
390         unsigned state =
391             isSet(WritableBit) << 2 | isSet(DirtyBit) << 1 | isValid();
392         char s = '?';
393         switch (state) {
394           case 0b111: s = 'M'; break;
395           case 0b011: s = 'O'; break;
396           case 0b101: s = 'E'; break;
397           case 0b001: s = 'S'; break;
398           case 0b000: s = 'I'; break;
399           default:    s = 'T'; break; // @TODO add other types
400         }
401         return csprintf("state: %x (%c) writable: %d readable: %d "
402             "dirty: %d prefetched: %d | %s", coherence, s,
403             isSet(WritableBit), isSet(ReadableBit), isSet(DirtyBit),
404             wasPrefetched(), TaggedEntry::print());
405     }
```


###
```cpp

 620     //@{
 621     /// Snoop flags
 622     /**
 623      * Set the cacheResponding flag. This is used by the caches to
 624      * signal another cache that they are responding to a request. A
 625      * cache will only respond to snoops if it has the line in either
 626      * Modified or Owned state. Note that on snoop hits we always pass
 627      * the line as Modified and never Owned. In the case of an Owned
 628      * line we proceed to invalidate all other copies.
 629      *
 630      * On a cache fill (see Cache::handleFill), we check hasSharers
 631      * first, ignoring the cacheResponding flag if hasSharers is set.
 632      * A line is consequently allocated as:
 633      *
 634      * hasSharers cacheResponding state
 635      * true       false           Shared
 636      * true       true            Shared
 637      * false      false           Exclusive
 638      * false      true            Modified
 639      */
 640     void setCacheResponding()
 641     {   
 642         assert(isRequest());
 643         assert(!flags.isSet(CACHE_RESPONDING));
 644         flags.set(CACHE_RESPONDING);
 645     }
 646     bool cacheResponding() const { return flags.isSet(CACHE_RESPONDING); }
 647     /**
 648      * On fills, the hasSharers flag is used by the caches in
 649      * combination with the cacheResponding flag, as clarified
 650      * above. If the hasSharers flag is not set, the packet is passing
 651      * writable. Thus, a response from a memory passes the line as
 652      * writable by default.
 653      *
 654      * The hasSharers flag is also used by upstream caches to inform a
 655      * downstream cache that they have the block (by calling
 656      * setHasSharers on snoop request packets that hit in upstream
 657      * cachs tags or MSHRs). If the snoop packet has sharers, a
 658      * downstream cache is prevented from passing a dirty line upwards
 659      * if it was not explicitly asked for a writable copy. See
 660      * Cache::satisfyCpuSideRequest.
 661      *
 662      * The hasSharers flag is also used on writebacks, in
 663      * combination with the WritbackClean or WritebackDirty commands,
 664      * to allocate the block downstream either as:
 665      *
 666      * command        hasSharers state
 667      * WritebackDirty false      Modified
 668      * WritebackDirty true       Owned
 669      * WritebackClean false      Exclusive
 670      * WritebackClean true       Shared
 671      */
 672     void setHasSharers()    { flags.set(HAS_SHARERS); }
 673     bool hasSharers() const { return flags.isSet(HAS_SHARERS); }

```


## Snoop 
```cpp
2517 // Express snooping requests to memside port
2518 void
2519 BaseCache::MemSidePort::recvTimingSnoopReq(PacketPtr pkt)
2520 {
2521     // Snoops shouldn't happen when bypassing caches
2522     assert(!cache->system->bypassCaches());
2523 
2524     // handle snooping requests
2525     cache->recvTimingSnoopReq(pkt);
2526 }
```


```cpp
1199 void
1200 Cache::recvTimingSnoopReq(PacketPtr pkt)
1201 {
1202     DPRINTF(CacheVerbose, "%s: for %s\n", __func__, pkt->print());
1203 
1204     // no need to snoop requests that are not in range
1205     if (!inRange(pkt->getAddr())) {
1206         return;
1207     }
1208 
1209     bool is_secure = pkt->isSecure();
1210     CacheBlk *blk = tags->findBlock(pkt->getAddr(), is_secure);
1211 
1212     Addr blk_addr = pkt->getBlockAddr(blkSize);
1213     MSHR *mshr = mshrQueue.findMatch(blk_addr, is_secure);
1214 
1215     // Update the latency cost of the snoop so that the crossbar can
1216     // account for it. Do not overwrite what other neighbouring caches
1217     // have already done, rather take the maximum. The update is
1218     // tentative, for cases where we return before an upward snoop
1219     // happens below.
1220     pkt->snoopDelay = std::max<uint32_t>(pkt->snoopDelay,
1221                                          lookupLatency * clockPeriod());
1222 
1223     // Inform request(Prefetch, CleanEvict or Writeback) from below of
1224     // MSHR hit, set setBlockCached.
1225     if (mshr && pkt->mustCheckAbove()) {
1226         DPRINTF(Cache, "Setting block cached for %s from lower cache on "
1227                 "mshr hit\n", pkt->print());
1228         pkt->setBlockCached();
1229         return;
1230     }
1231 
1232     // Let the MSHR itself track the snoop and decide whether we want
1233     // to go ahead and do the regular cache snoop
1234     if (mshr && mshr->handleSnoop(pkt, order++)) {
1235         DPRINTF(Cache, "Deferring snoop on in-service MSHR to blk %#llx (%s)."
1236                 "mshrs: %s\n", blk_addr, is_secure ? "s" : "ns",
1237                 mshr->print());
1238 
1239         if (mshr->getNumTargets() > numTarget)
1240             warn("allocating bonus target for snoop"); //handle later
1241         return;
1242     }
1243 
1244     //We also need to check the writeback buffers and handle those
1245     WriteQueueEntry *wb_entry = writeBuffer.findMatch(blk_addr, is_secure);
1246     if (wb_entry) {
1247         DPRINTF(Cache, "Snoop hit in writeback to addr %#llx (%s)\n",
1248                 pkt->getAddr(), is_secure ? "s" : "ns");
1249         // Expect to see only Writebacks and/or CleanEvicts here, both of
1250         // which should not be generated for uncacheable data.
1251         assert(!wb_entry->isUncacheable());
1252         // There should only be a single request responsible for generating
1253         // Writebacks/CleanEvicts.
1254         assert(wb_entry->getNumTargets() == 1);
1255         PacketPtr wb_pkt = wb_entry->getTarget()->pkt;
1256         assert(wb_pkt->isEviction() || wb_pkt->cmd == MemCmd::WriteClean);
1257 
1258         if (pkt->isEviction()) {
1259             // if the block is found in the write queue, set the BLOCK_CACHED
1260             // flag for Writeback/CleanEvict snoop. On return the snoop will
1261             // propagate the BLOCK_CACHED flag in Writeback packets and prevent
1262             // any CleanEvicts from travelling down the memory hierarchy.
1263             pkt->setBlockCached();
1264             DPRINTF(Cache, "%s: Squashing %s from lower cache on writequeue "
1265                     "hit\n", __func__, pkt->print());
1266             return;
1267         }
1268 
1269         // conceptually writebacks are no different to other blocks in
1270         // this cache, so the behaviour is modelled after handleSnoop,
1271         // the difference being that instead of querying the block
1272         // state to determine if it is dirty and writable, we use the
1273         // command and fields of the writeback packet
1274         bool respond = wb_pkt->cmd == MemCmd::WritebackDirty &&
1275             pkt->needsResponse();
1276         bool have_writable = !wb_pkt->hasSharers();
1277         bool invalidate = pkt->isInvalidate();
1278 
1279         if (!pkt->req->isUncacheable() && pkt->isRead() && !invalidate) {
1280             assert(!pkt->needsWritable());
1281             pkt->setHasSharers();
1282             wb_pkt->setHasSharers();
1283         }
1284 
1285         if (respond) {
1286             pkt->setCacheResponding();
1287 
1288             if (have_writable) {
1289                 pkt->setResponderHadWritable();
1290             }
1291 
1292             doTimingSupplyResponse(pkt, wb_pkt->getConstPtr<uint8_t>(),
1293                                    false, false);
1294         }
1295 
1296         if (invalidate && wb_pkt->cmd != MemCmd::WriteClean) {
1297             // Invalidation trumps our writeback... discard here
1298             // Note: markInService will remove entry from writeback buffer.
1299             markInService(wb_entry);
1300             delete wb_pkt;
1301         }
1302     }
1303 
1304     // If this was a shared writeback, there may still be
1305     // other shared copies above that require invalidation.
1306     // We could be more selective and return here if the
1307     // request is non-exclusive or if the writeback is
1308     // exclusive.
1309     uint32_t snoop_delay = handleSnoop(pkt, blk, true, false, false);
1310 
1311     // Override what we did when we first saw the snoop, as we now
1312     // also have the cost of the upwards snoops to account for
1313     pkt->snoopDelay = std::max<uint32_t>(pkt->snoopDelay, snoop_delay +
1314                                          lookupLatency * clockPeriod());
1315 }

```

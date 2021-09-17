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

### XXX{need recvTimingSnoopReq of the XBAR}
```cpp
 509 void
 510 CoherentXBar::recvTimingSnoopReq(PacketPtr pkt, PortID mem_side_port_id)
 511 {   
 512     DPRINTF(CoherentXBar, "%s: src %s packet %s\n", __func__,
 513             memSidePorts[mem_side_port_id]->name(), pkt->print());
 514     
 515     // update stats here as we know the forwarding will succeed
 516     unsigned int pkt_size = pkt->hasData() ? pkt->getSize() : 0;
 517     transDist[pkt->cmdToIndex()]++;
 518     snoops++;
 519     snoopTraffic += pkt_size;
 520     
 521     // we should only see express snoops from caches
 522     assert(pkt->isExpressSnoop());
 523     
 524     // set the packet header and payload delay, for now use forward latency
 525     // @todo Assess the choice of latency further
 526     calcPacketTiming(pkt, forwardLatency * clockPeriod());
 527     
 528     // remember if a cache has already committed to responding so we
 529     // can see if it changes during the snooping
 530     const bool cache_responding = pkt->cacheResponding();
 531     
 532     assert(pkt->snoopDelay == 0);
 533     
 534     if (snoopFilter) {
 535         // let the Snoop Filter work its magic and guide probing
 536         auto sf_res = snoopFilter->lookupSnoop(pkt);
 537         // the time required by a packet to be delivered through
 538         // the xbar has to be charged also with to lookup latency
 539         // of the snoop filter
 540         pkt->headerDelay += sf_res.second * clockPeriod();
 541         DPRINTF(CoherentXBar, "%s: src %s packet %s SF size: %i lat: %i\n",
 542                 __func__, memSidePorts[mem_side_port_id]->name(),
 543                 pkt->print(), sf_res.first.size(), sf_res.second);
 544         
 545         // forward to all snoopers
 546         forwardTiming(pkt, InvalidPortID, sf_res.first);
 547     } else {
 548         forwardTiming(pkt, InvalidPortID);
 549     }
 550     
 551     // add the snoop delay to our header delay, and then reset it
 552     pkt->headerDelay += pkt->snoopDelay;
 553     pkt->snoopDelay = 0;
 554     
 555     // if we can expect a response, remember how to route it
 556     if (!cache_responding && pkt->cacheResponding()) {
 557         assert(routeTo.find(pkt->req) == routeTo.end());
 558         routeTo[pkt->req] = mem_side_port_id;
 559     }
 560 
 561     // a snoop request came from a connected CPU-side-port device (one of
 562     // our memory-side ports), and if it is not coming from the CPU-side-port
 563     // device responsible for the address range something is
 564     // wrong, hence there is nothing further to do as the packet
 565     // would be going back to where it came from
 566     assert(findPort(pkt->getAddrRange()) == mem_side_port_id);
 567 }
```

The details about forwardTiming is described in the previous posting.
After forwarding the snoop request to the other component
connected to the XBar,
it should memorize the sender's identity (mem_side_port_id)
to the routeTo map, when the snoop request requires response.
Therefore, when the response for the snoop request packet is 
delivered to the XBar, 
it can figure out which entity send the snoop request
so that the response packet can be delivered to that entity.

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


## Generic way to handle snoop request
```cpp
 983 uint32_t
 984 Cache::handleSnoop(PacketPtr pkt, CacheBlk *blk, bool is_timing,
 985                    bool is_deferred, bool pending_inval)
 986 {
 987     DPRINTF(CacheVerbose, "%s: for %s\n", __func__, pkt->print());
 988     // deferred snoops can only happen in timing mode
 989     assert(!(is_deferred && !is_timing));
 990     // pending_inval only makes sense on deferred snoops
 991     assert(!(pending_inval && !is_deferred));
 992     assert(pkt->isRequest());
 993 
 994     // the packet may get modified if we or a forwarded snooper
 995     // responds in atomic mode, so remember a few things about the
 996     // original packet up front
 997     bool invalidate = pkt->isInvalidate();
 998     GEM5_VAR_USED bool needs_writable = pkt->needsWritable();
 999 
1000     // at the moment we could get an uncacheable write which does not
1001     // have the invalidate flag, and we need a suitable way of dealing
1002     // with this case
1003     panic_if(invalidate && pkt->req->isUncacheable(),
1004              "%s got an invalidating uncacheable snoop request %s",
1005              name(), pkt->print());
1006 
1007     uint32_t snoop_delay = 0;
1008 
1009     if (forwardSnoops) {
1010         // first propagate snoop upward to see if anyone above us wants to
1011         // handle it.  save & restore packet src since it will get
1012         // rewritten to be relative to CPU-side bus (if any)
1013         if (is_timing) {
1014             // copy the packet so that we can clear any flags before
1015             // forwarding it upwards, we also allocate data (passing
1016             // the pointer along in case of static data), in case
1017             // there is a snoop hit in upper levels
1018             Packet snoopPkt(pkt, true, true);
1019             snoopPkt.setExpressSnoop();
1020             // the snoop packet does not need to wait any additional
1021             // time
1022             snoopPkt.headerDelay = snoopPkt.payloadDelay = 0;
1023             cpuSidePort.sendTimingSnoopReq(&snoopPkt);
1024 
1025             // add the header delay (including crossbar and snoop
1026             // delays) of the upward snoop to the snoop delay for this
1027             // cache
1028             snoop_delay += snoopPkt.headerDelay;
1029 
1030             // If this request is a prefetch or clean evict and an upper level
1031             // signals block present, make sure to propagate the block
1032             // presence to the requestor.
1033             if (snoopPkt.isBlockCached()) {
1034                 pkt->setBlockCached();
1035             }
1036             // If the request was satisfied by snooping the cache
1037             // above, mark the original packet as satisfied too.
1038             if (snoopPkt.satisfied()) {
1039                 pkt->setSatisfied();
1040             }
1041 
1042             // Copy over flags from the snoop response to make sure we
1043             // inform the final destination
1044             pkt->copyResponderFlags(&snoopPkt);
1045         } else {
1046             bool already_responded = pkt->cacheResponding();
1047             cpuSidePort.sendAtomicSnoop(pkt);
1048             if (!already_responded && pkt->cacheResponding()) {
1049                 // cache-to-cache response from some upper cache:
1050                 // forward response to original requestor
1051                 assert(pkt->isResponse());
1052             }
1053         }
1054     }
```


### Checking if the current cache has the block associated with snoop packet
```cpp
1056     bool respond = false;
1057     bool blk_valid = blk && blk->isValid();
1058     if (pkt->isClean()) {
1059         if (blk_valid && blk->isSet(CacheBlk::DirtyBit)) {
1060             DPRINTF(CacheVerbose, "%s: packet (snoop) %s found block: %s\n",
1061                     __func__, pkt->print(), blk->print());
1062             PacketPtr wb_pkt =
1063                 writecleanBlk(blk, pkt->req->getDest(), pkt->id);
1064             PacketList writebacks;
1065             writebacks.push_back(wb_pkt);
1066 
1067             if (is_timing) {
1068                 // anything that is merely forwarded pays for the forward
1069                 // latency and the delay provided by the crossbar
1070                 Tick forward_time = clockEdge(forwardLatency) +
1071                     pkt->headerDelay;
1072                 doWritebacks(writebacks, forward_time);
1073             } else {
1074                 doWritebacksAtomic(writebacks);
1075             }
1076             pkt->setSatisfied();
1077         }
1078     } else if (!blk_valid) {
1079         DPRINTF(CacheVerbose, "%s: snoop miss for %s\n", __func__,
1080                 pkt->print());
1081         if (is_deferred) {
1082             // we no longer have the block, and will not respond, but a
1083             // packet was allocated in MSHR::handleSnoop and we have
1084             // to delete it
1085             assert(pkt->needsResponse());
1086 
1087             // we have passed the block to a cache upstream, that
1088             // cache should be responding
1089             assert(pkt->cacheResponding());
1090 
1091             delete pkt;
1092         }
1093         return snoop_delay;
1094     } else {
1095         DPRINTF(Cache, "%s: snoop hit for %s, old state is %s\n", __func__,
1096                 pkt->print(), blk->print());
1097 
1098         // We may end up modifying both the block state and the packet (if
1099         // we respond in atomic mode), so just figure out what to do now
1100         // and then do it later. We respond to all snoops that need
1101         // responses provided we have the block in dirty state. The
1102         // invalidation itself is taken care of below. We don't respond to
1103         // cache maintenance operations as this is done by the destination
1104         // xbar.
1105         respond = blk->isSet(CacheBlk::DirtyBit) && pkt->needsResponse();
1106 
1107         chatty_assert(!(isReadOnly && blk->isSet(CacheBlk::DirtyBit)),
1108             "Should never have a dirty block in a read-only cache %s\n",
1109             name());
1110     }
```
First of all, it checks the currently searched block is valid or not.
When the current cache doesn't have a valid cache block for the 
snoop request address,
the blk_valid flag is set as false and the 
line 1078-1093 will be executed. 
When there is no matching cache block in this level of cache,
then it just returns a measured snoop_delay.

However, when the packet is not the clean packet 
but hit in the current cache, 
the rest of the condition will be executed (Line 1094-1110). 
Because the current cache has the requested block,
it should check whether the current block is in clean state.
The DirtyBit of the cache block determines it.
Also, it should check whether the packet required response.
When both conditions are met, 
then the respond flag is set and will further process the snoop request 
in the below code. 




```cpp
1112     // Invalidate any prefetch's from below that would strip write permissions
1113     // MemCmd::HardPFReq is only observed by upstream caches.  After missing
1114     // above and in it's own cache, a new MemCmd::ReadReq is created that
1115     // downstream caches observe.
1116     if (pkt->mustCheckAbove()) {
1117         DPRINTF(Cache, "Found addr %#llx in upper level cache for snoop %s "
1118                 "from lower cache\n", pkt->getAddr(), pkt->print());
1119         pkt->setBlockCached();
1120         return snoop_delay;
1121     }
1122 
1123     if (pkt->isRead() && !invalidate) {
1124         // reading without requiring the line in a writable state
1125         assert(!needs_writable);
1126         pkt->setHasSharers();
1127 
1128         // if the requesting packet is uncacheable, retain the line in
1129         // the current state, otherwhise unset the writable flag,
1130         // which means we go from Modified to Owned (and will respond
1131         // below), remain in Owned (and will respond below), from
1132         // Exclusive to Shared, or remain in Shared
1133         if (!pkt->req->isUncacheable()) {
1134             blk->clearCoherenceBits(CacheBlk::WritableBit);
1135         }
1136         DPRINTF(Cache, "new state is %s\n", blk->print());
1137     }
```
Before responding to the snoop, 
it first checks two conditions: checking above and read access. 
\xxx{checking above should be handled}
Also, when the snoop packet is generated 
because of the read operation from other components,
then it should invoke setHasSharers of the packet 
to let the sender know that some caches has the 
shared read only cache block. 

### respond to the snoop request
```cpp
1138 
1139     if (respond) {
1140         // prevent anyone else from responding, cache as well as
1141         // memory, and also prevent any memory from even seeing the
1142         // request
1143         pkt->setCacheResponding();
1144         if (!pkt->isClean() && blk->isSet(CacheBlk::WritableBit)) {
1145             // inform the cache hierarchy that this cache had the line
1146             // in the Modified state so that we avoid unnecessary
1147             // invalidations (see Packet::setResponderHadWritable)
1148             pkt->setResponderHadWritable();
1149 
1150             // in the case of an uncacheable request there is no point
1151             // in setting the responderHadWritable flag, but since the
1152             // recipient does not care there is no harm in doing so
1153         } else {
1154             // if the packet has needsWritable set we invalidate our
1155             // copy below and all other copies will be invalidates
1156             // through express snoops, and if needsWritable is not set
1157             // we already called setHasSharers above
1158         }
1159 
1160         // if we are returning a writable and dirty (Modified) line,
1161         // we should be invalidating the line
1162         panic_if(!invalidate && !pkt->hasSharers(),
1163                  "%s is passing a Modified line through %s, "
1164                  "but keeping the block", name(), pkt->print());
1165 
1166         if (is_timing) {
1167             doTimingSupplyResponse(pkt, blk->data, is_deferred, pending_inval);
1168         } else {
1169             pkt->makeAtomicResponse();
1170             // packets such as upgrades do not actually have any data
1171             // payload
1172             if (pkt->hasData())
1173                 pkt->setDataFromBlock(blk->data, blkSize);
1174         }
1175 
1176         // When a block is compressed, it must first be decompressed before
1177         // being read, and this increases the snoop delay.
1178         if (compressor && pkt->isRead()) {
1179             snoop_delay += compressor->getDecompressionLatency(blk);
1180         }
1181     }
1182 
1183     if (!respond && is_deferred) {
1184         assert(pkt->needsResponse());
1185         delete pkt;
1186     }
```

When there is no need for respond, 
it just deletes the snoop packet and returns.
However, on the other hand,
when the current cache owns or modified the cache block
requested by the snoop packet,
it should respond. 
The first think to be done is make 
the sender know that current cache 
contains the request cache block and will respond.
This is done by setting the flag of the packet 
through the setCacheResponding function.
Note that this might not be possible implementation
because the snooping packet might be concurrently checked
by the multiple entries connected to the XBar.

Anyway, when it needs to respond,
which means that the selected cache block 
is set as dirty and the request packet requires response,
there are two conditions for the matching block
regarding its status: owned or modified. 
When the cache block is in the owned state, 
it means that there could be multiple sharers 
for the dirty block but with the same content, and 
the current cache unit has responsibility to flush out 
the dirty block to the memory when one of its sharers 
including itself is evicted or modified. 
However, the modified condition means that 
the current cache has sole copy and modified 
in its cache. 
To distinguish the modified state from owned,
it invokes setResponderHadWritable
and set RESPONDER_HAD_WRITABLE flag.

### doTimingSupplyResponse: generate and send the snoop response
```cpp
 938 void
 939 Cache::doTimingSupplyResponse(PacketPtr req_pkt, const uint8_t *blk_data,
 940                               bool already_copied, bool pending_inval)
 941 {
 942     // sanity check
 943     assert(req_pkt->isRequest());
 944     assert(req_pkt->needsResponse());
 945 
 946     DPRINTF(Cache, "%s: for %s\n", __func__, req_pkt->print());
 947     // timing-mode snoop responses require a new packet, unless we
 948     // already made a copy...
 949     PacketPtr pkt = req_pkt;
 950     if (!already_copied)
 951         // do not clear flags, and allocate space for data if the
 952         // packet needs it (the only packets that carry data are read
 953         // responses)
 954         pkt = new Packet(req_pkt, false, req_pkt->isRead());
 955 
 956     assert(req_pkt->req->isUncacheable() || req_pkt->isInvalidate() ||
 957            pkt->hasSharers());
 958     pkt->makeTimingResponse();
 959     if (pkt->isRead()) {
 960         pkt->setDataFromBlock(blk_data, blkSize);
 961     }
 962     if (pkt->cmd == MemCmd::ReadResp && pending_inval) {
 963         // Assume we defer a response to a read from a far-away cache
 964         // A, then later defer a ReadExcl from a cache B on the same
 965         // bus as us. We'll assert cacheResponding in both cases, but
 966         // in the latter case cacheResponding will keep the
 967         // invalidation from reaching cache A. This special response
 968         // tells cache A that it gets the block to satisfy its read,
 969         // but must immediately invalidate it.
 970         pkt->cmd = MemCmd::ReadRespWithInvalidate;
 971     }
 972     // Here we consider forward_time, paying for just forward latency and
 973     // also charging the delay provided by the xbar.
 974     // forward_time is used as send_time in next allocateWriteBuffer().
 975     Tick forward_time = clockEdge(forwardLatency) + pkt->headerDelay;
 976     // Here we reset the timing of the packet.
 977     pkt->headerDelay = pkt->payloadDelay = 0;
 978     DPRINTF(CacheVerbose, "%s: created response: %s tick: %lu\n", __func__,
 979             pkt->print(), forward_time);
 980     memSidePort.schedTimingSnoopResp(pkt, forward_time);
 981 }
```

Based on the request type, it generates the response packet. 
The response packet for the read operation 
requires the data cached in the current cache to share it 
to the snoop requester. 
However, for the other request, 
the current cache data would not be necessary.
When the packet is populated,
it sends to the requester through the memSidePort.
It invokes the schedTimingSnoopResp function
and schedule the sending the snoop response packet 
to the requester. 

### End of the handleSnoop (also recvTimingSnoopReq).
Because the handleSnoop is the last function 
invoked by the recvTimingSnoopReq function,
when one ends the other also ends. 

```cpp
1187 
1188     // Do this last in case it deallocates block data or something
1189     // like that
1190     if (blk_valid && invalidate) {
1191         invalidateBlock(blk);
1192         DPRINTF(Cache, "new state is %s\n", blk->print());
1193     }
1194 
1195     return snoop_delay;
1196 }
```


## recvTimingSnoopResp of the XBar: receiving response from the other cache
```cpp
 569 bool
 570 CoherentXBar::recvTimingSnoopResp(PacketPtr pkt, PortID cpu_side_port_id)
 571 {
 572     // determine the source port based on the id
 573     ResponsePort* src_port = cpuSidePorts[cpu_side_port_id];
 574 
 575     // get the destination
 576     const auto route_lookup = routeTo.find(pkt->req);
 577     assert(route_lookup != routeTo.end());
 578     const PortID dest_port_id = route_lookup->second;
 579     assert(dest_port_id != InvalidPortID);
 580 
 581     // determine if the response is from a snoop request we
 582     // created as the result of a normal request (in which case it
 583     // should be in the outstandingSnoop), or if we merely forwarded
 584     // someone else's snoop request
 585     const bool forwardAsSnoop = outstandingSnoop.find(pkt->req) ==
 586         outstandingSnoop.end();
 587 
 588     // test if the crossbar should be considered occupied for the
 589     // current port, note that the check is bypassed if the response
 590     // is being passed on as a normal response since this is occupying
 591     // the response layer rather than the snoop response layer
 592     if (forwardAsSnoop) {
 593         assert(dest_port_id < snoopLayers.size());
 594         if (!snoopLayers[dest_port_id]->tryTiming(src_port)) {
 595             DPRINTF(CoherentXBar, "%s: src %s packet %s BUSY\n", __func__,
 596                     src_port->name(), pkt->print());
 597             return false;
 598         }
 599     } else {
 600         // get the memory-side port that mirrors this CPU-side port internally
 601         RequestPort* snoop_port = snoopRespPorts[cpu_side_port_id];
 602         assert(dest_port_id < respLayers.size());
 603         if (!respLayers[dest_port_id]->tryTiming(snoop_port)) {
 604             DPRINTF(CoherentXBar, "%s: src %s packet %s BUSY\n", __func__,
 605                     snoop_port->name(), pkt->print());
 606             return false;
 607         }
 608     }
 609 
 610     DPRINTF(CoherentXBar, "%s: src %s packet %s\n", __func__,
 611             src_port->name(), pkt->print());
 612 
 613     // store size and command as they might be modified when
 614     // forwarding the packet
 615     unsigned int pkt_size = pkt->hasData() ? pkt->getSize() : 0;
 616     unsigned int pkt_cmd = pkt->cmdToIndex();
 617 
 618     // responses are never express snoops
 619     assert(!pkt->isExpressSnoop());
 620 
 621     // a snoop response sees the snoop response latency, and if it is
 622     // forwarded as a normal response, the response latency
 623     Tick xbar_delay =
 624         (forwardAsSnoop ? snoopResponseLatency : responseLatency) *
 625         clockPeriod();
 626 
 627     // set the packet header and payload delay
 628     calcPacketTiming(pkt, xbar_delay);
 629 
 630     // determine how long to be crossbar layer is busy
 631     Tick packetFinishTime = clockEdge(headerLatency) + pkt->payloadDelay;
 632 
 633     // forward it either as a snoop response or a normal response
 634     if (forwardAsSnoop) {
 635         // this is a snoop response to a snoop request we forwarded,
 636         // e.g. coming from the L1 and going to the L2, and it should
 637         // be forwarded as a snoop response
 638 
 639         if (snoopFilter) {
 640             // update the probe filter so that it can properly track the line
 641             snoopFilter->updateSnoopForward(pkt,
 642                             *cpuSidePorts[cpu_side_port_id],
 643                             *memSidePorts[dest_port_id]);
 644         }
 645 
 646         GEM5_VAR_USED bool success =
 647             memSidePorts[dest_port_id]->sendTimingSnoopResp(pkt);
 648         pktCount[cpu_side_port_id][dest_port_id]++;
 649         pktSize[cpu_side_port_id][dest_port_id] += pkt_size;
 650         assert(success);
 651 
 652         snoopLayers[dest_port_id]->succeededTiming(packetFinishTime);
 653     } else {
 654         // we got a snoop response on one of our CPU-side ports,
 655         // i.e. from a coherent requestor connected to the crossbar, and
 656         // since we created the snoop request as part of recvTiming,
 657         // this should now be a normal response again
 658         outstandingSnoop.erase(pkt->req);
 659 
 660         // this is a snoop response from a coherent requestor, hence it
 661         // should never go back to where the snoop response came from,
 662         // but instead to where the original request came from
 663         assert(cpu_side_port_id != dest_port_id);
 664 
 665         if (snoopFilter) {
 666             // update the probe filter so that it can properly track
 667             // the line
 668             snoopFilter->updateSnoopResponse(pkt,
 669                         *cpuSidePorts[cpu_side_port_id],
 670                         *cpuSidePorts[dest_port_id]);
 671         }
 672 
 673         DPRINTF(CoherentXBar, "%s: src %s packet %s FWD RESP\n", __func__,
 674                 src_port->name(), pkt->print());
 675 
 676         // as a normal response, it should go back to a requestor through
 677         // one of our CPU-side ports, we also pay for any outstanding
 678         // header latency
 679         Tick latency = pkt->headerDelay;
 680         pkt->headerDelay = 0;
 681         cpuSidePorts[dest_port_id]->schedTimingResp(pkt,
 682                                     curTick() + latency);
 683 
 684         respLayers[dest_port_id]->succeededTiming(packetFinishTime);
 685     }
 686 
 687     // remove the request from the routing table
 688     routeTo.erase(route_lookup);
 689 
 690     // stats updates
 691     transDist[pkt_cmd]++;
 692     snoops++;
 693     snoopTraffic += pkt_size;
 694 
 695     return true;
 696 }


```


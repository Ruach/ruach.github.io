
## Cache internal class hierarchies in GEM5
```cpp
  92 /**
  93  * A basic cache interface. Implements some common functions for speed.
  94  */
  95 class BaseCache : public ClockedObject
  96 {
......
 349     /** Tag and data Storage */
 350     BaseTags *tags;
```

```cpp
 70 /**
 71  * A common base class of Cache tagstore objects.
 72  */
 73 class BaseTags : public ClockedObject
 74 {
......
 88     /** Indexing policy */
 89     BaseIndexingPolicy *indexingPolicy;
......
102     /** The data blocks, 1 per cache block. */
103     std::unique_ptr<uint8_t[]> dataBlks;
```

The main cache structure called BaseCache contains member field tags (object of BaseTags)
The BaseTags class contains the actual data blocks for maintaining data to the cache.
Also, it has BaseIndexingPolicy that determines which entry should be selected or evicted 
as a result of cache access operations (including cache read and write). 

```cpp
60 /**
 61  * A common base class for indexing table locations. Classes that inherit
 62  * from it determine hash functions that should be applied based on the set
 63  * and way. These functions are then applied to re-map the original values.
 64  * @sa  \ref gem5MemorySystem "gem5 Memory System"
 65  */
 66 class BaseIndexingPolicy : public SimObject
 67 {
 68   protected:
 69     /**
 70      * The associativity.
 71      */
 72     const unsigned assoc;
 73 
 74     /**
 75      * The number of sets in the cache.
 76      */
 77     const uint32_t numSets;
 78 
 79     /**
 80      * The amount to shift the address to get the set.
 81      */
 82     const int setShift;
 83 
 84     /**
 85      * Mask out all bits that aren't part of the set index.
 86      */
 87     const unsigned setMask;
 88 
 89     /**
 90      * The cache sets.
 91      */
 92     std::vector<std::vector<ReplaceableEntry*>> sets;
```

Note that the BaseIndexingPolicy contains sets 
consisting of multiple entries of ReplaceableEntry. 
The CacheBlk will be stored in the sets member field
because the CacheBlk is a child of ReplaceableEntry class. 
Also, sets can be indexed with set and way to provide 
nomenclature of the cache. 

### CacheBlk the basic unit of each cache block entry
```cpp
 65 /**
 66  * A Basic Cache block.
 67  * Contains information regarding its coherence, prefetching status, as
 68  * well as a pointer to its data.
 69  */
 70 class CacheBlk : public TaggedEntry
```

```cpp
 41 /**
 42  * A tagged entry is an entry containing a tag. Each tag is accompanied by a
 43  * secure bit, which informs whether it belongs to a secure address space.
 44  * A tagged entry's contents are only relevant if it is marked as valid.
 45  */
 46 class TaggedEntry : public ReplaceableEntry
```

```cpp
 53 /**
 54  * A replaceable entry is a basic entry in a 2d table-like structure that needs
 55  * to have replacement functionality. This entry is located in a specific row
 56  * and column of the table (set and way in cache nomenclature), which are
 57  * stored within the entry itself.
 58  *
 59  * It contains the replacement data pointer, which must be instantiated by the
 60  * replacement policy before being used.
 61  * @sa Replacement Policies
 62  */
 63 class ReplaceableEntry
```

The cache block maintains three important data related with one cache entry:
coherence information, prefetching status, and pointer to the data.
Therefore, let's take a look at the structure and interface 
required for managing those information.
**Remaining question: Then where the data exactly is stored? in the CacheBlk object? or 
in the dataBlks member field of the tags?**

## Cache management

### Initializing cache blocks
```cpp
  79 BaseCache::BaseCache(const BaseCacheParams &p, unsigned blk_size)
  80     : ClockedObject(p),
  81       cpuSidePort (p.name + ".cpu_side_port", this, "CpuSidePort"),
  82       memSidePort(p.name + ".mem_side_port", this, "MemSidePort"),
  83       mshrQueue("MSHRs", p.mshrs, 0, p.demand_mshr_reserve, p.name),
  84       writeBuffer("write buffer", p.write_buffers, p.mshrs, p.name),
  85       tags(p.tags),
  86       compressor(p.compressor),
  87       prefetcher(p.prefetcher),
  88       writeAllocator(p.write_allocator),
  89       writebackClean(p.writeback_clean),
  90       tempBlockWriteback(nullptr),
  91       writebackTempBlockAtomicEvent([this]{ writebackTempBlockAtomic(); },
  92                                     name(), false,
  93                                     EventBase::Delayed_Writeback_Pri),
  94       blkSize(blk_size),
  95       lookupLatency(p.tag_latency),
  96       dataLatency(p.data_latency),
  97       forwardLatency(p.tag_latency),
  98       fillLatency(p.data_latency),
  99       responseLatency(p.response_latency),
 100       sequentialAccess(p.sequential_access),
 101       numTarget(p.tgts_per_mshr),
 102       forwardSnoops(true),
 103       clusivity(p.clusivity),
 104       isReadOnly(p.is_read_only),
 105       replaceExpansions(p.replace_expansions),
 106       moveContractions(p.move_contractions),
 107       blocked(0),
 108       order(0),
 109       noTargetMSHR(nullptr),
 110       missCount(p.max_miss_count),
 111       addrRanges(p.addr_ranges.begin(), p.addr_ranges.end()),
 112       system(p.system),
 113       stats(*this)
 114 {
 115     // the MSHR queue has no reserve entries as we check the MSHR
 116     // queue on every single allocation, whereas the write queue has
 117     // as many reserve entries as we have MSHRs, since every MSHR may
 118     // eventually require a writeback, and we do not check the write
 119     // buffer before committing to an MSHR
 120 
 121     // forward snoops is overridden in init() once we can query
 122     // whether the connected requestor is actually snooping or not
 123 
 124     tempBlock = new TempCacheBlk(blkSize);
 125 
 126     tags->tagsInit();
 127     if (prefetcher)
 128         prefetcher->setCache(this);
 129 
 130     fatal_if(compressor && !dynamic_cast<CompressedTags*>(tags),
 131         "The tags of compressed cache %s must derive from CompressedTags",
 132         name());
 133     warn_if(!compressor && dynamic_cast<CompressedTags*>(tags),
 134         "Compressed cache %s does not have a compression algorithm", name());
 135     if (compressor)
```

When the BaseCache is constructed, 
it initializes its member field tags by passing the parameters
required for initializing the BaseTags class.
Because we are currently dealing with the BaseSetAssoc class which 
inherits the BaseTags class,
its constructor will be invoked first instead of the BaseTags's constructor. 

```cpp
 55 BaseSetAssoc::BaseSetAssoc(const Params &p)
 56     :BaseTags(p), allocAssoc(p.assoc), blks(p.size / p.block_size),
 57      sequentialAccess(p.sequential_access),
 58      replacementPolicy(p.replacement_policy)
 59 {
 60     // There must be a indexing policy
 61     fatal_if(!p.indexing_policy, "An indexing policy is required");
 62 
 63     // Check parameters
 64     if (blkSize < 4 || !isPowerOf2(blkSize)) {
 65         fatal("Block size must be at least 4 and a power of 2");
 66     }
 67 }
 68
 69 void
 70 BaseSetAssoc::tagsInit()
 71 {
 72     // Initialize all blocks
 73     for (unsigned blk_index = 0; blk_index < numBlocks; blk_index++) {
 74         // Locate next cache block
 75         CacheBlk* blk = &blks[blk_index];
 76 
 77         // Link block to indexing policy
 78         indexingPolicy->setEntry(blk, blk_index);
 79 
 80         // Associate a data chunk to the block
 81         blk->data = &dataBlks[blkSize*blk_index];
 82 
 83         // Associate a replacement data entry to the block
 84         blk->replacementData = replacementPolicy->instantiateEntry();
 85     }
 86 }
```
When the BaseSetAssoc is populated, it initializes the blk member field 
with (p.size / p.block_size) entries. 
After that, the constructor of the BaseCache invokes the tagsInit function
implemented in the BaseSetAssoc class. 
As shown in the above code, 
it select one CacheBlk from the blk memeber field of the BaseSetAssoc. 

```cpp
 80 void
 81 BaseIndexingPolicy::setEntry(ReplaceableEntry* entry, const uint64_t index)
 82 {
 83     // Calculate set and way from entry index
 84     const std::lldiv_t div_result = std::div((long long)index, assoc);
 85     const uint32_t set = div_result.quot;
 86     const uint32_t way = div_result.rem;
 87 
 88     // Sanity check
 89     assert(set < numSets);
 90 
 91     // Assign a free pointer
 92     sets[set][way] = entry;
 93 
 94     // Inform the entry its position
 95     entry->setPosition(set, way);
 96 }
```

The setEntry function of the indexingPolicy will be invoked next 
so that it associates the CacheBlk in the Tag class 
to the sets member field of the indexingPolicy

### Map datablk to cacheblk 
When the BaseSetAssoc object is constructed, 
it invoked its parent's constructor BaseTags with the parameter. 
```cpp
 61 BaseTags::BaseTags(const Params &p)
 62     : ClockedObject(p), blkSize(p.block_size), blkMask(blkSize - 1),
 63       size(p.size), lookupLatency(p.tag_latency),
 64       system(p.system), indexingPolicy(p.indexing_policy),
 65       warmupBound((p.warmup_percentage/100.0) * (p.size / p.block_size)),
 66       warmedUp(false), numBlocks(p.size / p.block_size),
 67       dataBlks(new uint8_t[p.size]), // Allocate data storage in one big chunk
 68       stats(*this)
 69 {
 70     registerExitCallback([this]() { cleanupRefs(); });
 71 }
```

You might remember that the BaseTags class contains dataBlks member field.
Here the constructor initializes the dataBlks to have 
(p.size / p.block_size) entries for storing the cache data. 
Note that the number of entries of the dataBlks and the blk are same
because one dataBlk is associated with one CacheBlk. 

```cpp
 69 void
 70 BaseSetAssoc::tagsInit()
 71 {
 72     // Initialize all blocks
 73     for (unsigned blk_index = 0; blk_index < numBlocks; blk_index++) {
 74         // Locate next cache block
 75         CacheBlk* blk = &blks[blk_index];
 76
 77         // Link block to indexing policy
 78         indexingPolicy->setEntry(blk, blk_index);
 79
 80         // Associate a data chunk to the block
 81         blk->data = &dataBlks[blkSize*blk_index];
```

When you go back to the tagsInit, 
you can find that one dataBlks having blkSize size 
is mapped to the one CacheBlk.
Because this CacheBlk is mapped to particular way of one set,
the data will be also associated with that cache entry.
To summary, the BaseCache maintains the tag.
And the tag provides cache storage and cacheblks to the 
BaseIndexingPolicy object.
Conceptually, the cache is maintained by the 
BaseIndexingPolicy class which maintains the cache
with set and ways indexing.


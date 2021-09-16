
## Class Hierarchies of BaseXBar

### BaseXBar: base class for all variants of XBar
```cpp
 62 /**
 63  * The base crossbar contains the common elements of the non-coherent
 64  * and coherent crossbar. It is an abstract class that does not have
 65  * any of the functionality relating to the actual reception and
 66  * transmission of packets, as this is left for the subclasses.
 67  *
 68  * The BaseXBar is responsible for the basic flow control (busy or
 69  * not), the administration of retries, and the address decoding.
 70  */
 71 class BaseXBar : public ClockedObject
 72 {
 ```
 The BaseXBar is an abstract class providing generic interfaces 
 required for XBar interconnection network. 
 Therefore, it doesn't have specific implementation for 
 receiving and sending the packets 
 in between the caches and memory. 
 For example, it provides a function that matches 
 address of the request to one specific port address 
 to deliver the packet to the unit 
 who has responsibility for processing it. 
 I will take a look at those interfaces after explaining the other classes first.


### Layer: base class for all layers in the XBar
```cpp
 76     /**
 77      * A layer is an internal crossbar arbitration point with its own
 78      * flow control. Each layer is a converging multiplexer tree. By
 79      * instantiating one layer per destination port (and per packet
 80      * type, i.e. request, response, snoop request and snoop
 81      * response), we model full crossbar structures like AXI, ACE,
 82      * PCIe, etc.
 83      *
 84      * The template parameter, PortClass, indicates the destination
 85      * port type for the layer. The retry list holds either memory-side ports
 86      * or CPU-side ports, depending on the direction of the
 87      * layer. Thus, a request layer has a retry list containing
 88      * CPU-side ports, whereas a response layer holds memory-side ports.
 89      */
 90     template <typename SrcType, typename DstType>
 91     class Layer : public Drainable, public statistics::Group
 92     {
 93 
 94       public:
 95 
 96         /**
 97          * Create a layer and give it a name. The layer uses
 98          * the crossbar an event manager.
 99          *
100          * @param _port destination port the layer converges at
101          * @param _xbar the crossbar this layer belongs to
102          * @param _name the layer's name
103          */
104         Layer(DstType& _port, BaseXBar& _xbar, const std::string& _name);
```

Although the BaseXBar contains all the cpuSidePorts and memSidePorts,
the concept of layer is applied for the XBar to manage 
communication channel in between 
different ports connected to the XBar.
Also, the Layer class is used for the base class for the 
three different types of layer based on the operation:
request, response, and snoop.
You can see that all Layer requires _port 
to which this layer is connected, and 
_xbar where the layers belong to. 


```cpp
237     class ReqLayer : public Layer<ResponsePort, RequestPort>
238     {
239       public:
240         /**
241          * Create a request layer and give it a name.
242          *
243          * @param _port destination port the layer converges at
244          * @param _xbar the crossbar this layer belongs to
245          * @param _name the layer's name
246          */
247         ReqLayer(RequestPort& _port, BaseXBar& _xbar,
248         const std::string& _name) :
249             Layer(_port, _xbar, _name)
250         {}
```


```cpp
260     class RespLayer : public Layer<RequestPort, ResponsePort>
261     {
262       public:
263         /**
264          * Create a response layer and give it a name.
265          *
266          * @param _port destination port the layer converges at
267          * @param _xbar the crossbar this layer belongs to
268          * @param _name the layer's name
269          */
270         RespLayer(ResponsePort& _port, BaseXBar& _xbar,
271                   const std::string& _name) :
272             Layer(_port, _xbar, _name)
273         {}
```


```cpp
283     class SnoopRespLayer : public Layer<ResponsePort, RequestPort>
284     {
285       public:
286         /**
287          * Create a snoop response layer and give it a name.
288          *
289          * @param _port destination port the layer converges at
290          * @param _xbar the crossbar this layer belongs to
291          * @param _name the layer's name
292          */
293         SnoopRespLayer(RequestPort& _port, BaseXBar& _xbar,
294                        const std::string& _name) :
295             Layer(_port, _xbar, _name)
296         {}
```

## Class Hierarchies of CoherentXBar
```cpp
59 /**
 60  * A coherent crossbar connects a number of (potentially) snooping
 61  * requestors and responders, and routes the request and response packets
 62  * based on the address, and also forwards all requests to the
 63  * snoopers and deals with the snoop responses.
 64  *
 65  * The coherent crossbar can be used as a template for modelling QPI,
 66  * HyperTransport, ACE and coherent OCP buses, and is typically used
 67  * for the L1-to-L2 buses and as the main system interconnect.  @sa
 68  * \ref gem5MemorySystem "gem5 Memory System"
 69  */
 70 class CoherentXBar : public BaseXBar
```
When the caches are shared among multiple processing units,
it should provide the coherency in between copied cache entries.
For that purpose, the CoherentXbar is implemented.
It inherits the BaseXBar class. 
Because the coherency is not provided by the BaseXbar class,
it requires additional implementations in the CoherentXbar class.

As the cache defines the CpuSidePort and MemSidePort 
to send and receive packets through the port, 
the XBar required its own Port class to 
process all packets going through the XBar.

### CoherentXBarResponsePort
```cpp
 83     /**
 84      * Declaration of the coherent crossbar CPU-side port type, one will
 85      * be instantiated for each of the mem_side_ports connecting to the
 86      * crossbar.
 87      */
 88     class CoherentXBarResponsePort : public QueuedResponsePort
 89     {
 90 
 91       private:
 92 
 93         /** A reference to the crossbar to which this port belongs. */
 94         CoherentXBar &xbar;
 95 
 96         /** A normal packet queue used to store responses. */
 97         RespPacketQueue queue;
 98 
 99       public:
100 
101         CoherentXBarResponsePort(const std::string &_name,
102                              CoherentXBar &_xbar, PortID _id)
103             : QueuedResponsePort(_name, &_xbar, queue, _id), xbar(_xbar),
104               queue(_xbar, *this)
105         { }
106       
107       protected:
108         
109         bool
110         recvTimingReq(PacketPtr pkt) override
111         {   
112             return xbar.recvTimingReq(pkt, id);
113         }
```
The most important function of the receiving port is the recvTimingReq. 
The CoherentXBarResponsePort also implements this function
because this port is used to receive packet from the other units. 


### CoherentXBarRequestPort
```cpp
147     /**
148      * Declaration of the coherent crossbar memory-side port type, one will be
149      * instantiated for each of the CPU-side-port interfaces connecting to the
150      * crossbar.
151      */
152     class CoherentXBarRequestPort : public RequestPort
153     {
154       private:
155         /** A reference to the crossbar to which this port belongs. */
156         CoherentXBar &xbar;
157 
158       public:
159 
160         CoherentXBarRequestPort(const std::string &_name,
161                               CoherentXBar &_xbar, PortID _id)
162             : RequestPort(_name, &_xbar, _id), xbar(_xbar)
163         { }
166 
167         /**
168          * Determine if this port should be considered a snooper. For
169          * a coherent crossbar memory-side port this is always true.
170          *
171          * @return a boolean that is true if this port is snooping
172          */
173         bool isSnooping() const override { return true; }
174 
175         bool
176         recvTimingResp(PacketPtr pkt) override
177         {
178             return xbar.recvTimingResp(pkt, id);
179         }
......
200         void recvReqRetry() override { xbar.recvReqRetry(id); }
201 
202     };
```

### SnoopRespPort
```cpp
204     /**
205      * Internal class to bridge between an incoming snoop response
206      * from a CPU-side port and forwarding it through an outgoing
207      * CPU-side port. It is effectively a dangling memory-side port.
208      */
209     class SnoopRespPort : public RequestPort
210     {
211 
212       private:
213 
214         /** The port which we mirror internally. */
215         QueuedResponsePort& cpuSidePort;
216 
217       public:
218 
219         /**
220          * Create a snoop response port that mirrors a given CPU-side port.
221          */
222         SnoopRespPort(QueuedResponsePort& cpu_side_port,
223                       CoherentXBar& _xbar) :
224             RequestPort(cpu_side_port.name() + ".snoopRespPort", &_xbar),
225             cpuSidePort(cpu_side_port) { }

```


## Connecting ports
```python
143     def createCacheHierarchy(self):
144         # Create an L3 cache (with crossbar)
145         self.l3bus = L2XBar(width = 64,
146                             snoop_filter = SnoopFilter(max_capacity='32MB'))
147 
148         for cpu in self.cpu:
149             # Create a memory bus, a coherent crossbar, in this case
150             cpu.l2bus = L2XBar()
151 
152             # Create an L1 instruction and data cache
153             cpu.icache = L1ICache()
154             cpu.dcache = L1DCache()
155             cpu.mmucache = MMUCache()
156 
157             # Connect the instruction and data caches to the CPU
158             cpu.icache.connectCPU(cpu)
159             cpu.dcache.connectCPU(cpu)
160             cpu.mmucache.connectCPU(cpu)
161 
162             # Hook the CPU ports up to the l2bus
163             cpu.icache.connectBus(cpu.l2bus)
164             cpu.dcache.connectBus(cpu.l2bus)
165             cpu.mmucache.connectBus(cpu.l2bus)
166 
167             # Create an L2 cache and connect it to the l2bus
168             cpu.l2cache = L2Cache()
169             cpu.l2cache.connectCPUSideBus(cpu.l2bus)
170 
171             # Connect the L2 cache to the L3 bus
172             cpu.l2cache.connectMemSideBus(self.l3bus)
173 
174         self.l3cache = L3Cache()
175         self.l3cache.connectCPUSideBus(self.l3bus)
176 
177         # Connect the L3 cache to the membus
178         self.l3cache.connectMemSideBus(self.membus)
```

As shown in the above code, 
l3 cache is connected with two different components of the system.
First, it's CPUSideBus is connected to the l3bus 
which is the CoherencyXBar.
Note that the other side of the l3bus is connected with the
L2 cache (Line 172).
And the L3 cache should be connected to the memory 
through the membus of the system (line 178).


```python
147 # We use a coherent crossbar to connect multiple requestors to the L2
148 # caches. Normally this crossbar would be part of the cache itself.
149 class L2XBar(CoherentXBar):
150     # 256-bit crossbar by default
151     width = 32
152 
153     # Assume that most of this is covered by the cache latencies, with
154     # no more than a single pipeline stage for any packet.
155     frontend_latency = 1
156     forward_latency = 0
157     response_latency = 1
158     snoop_response_latency = 1
159 
160     # Use a snoop-filter by default, and set the latency to zero as
161     # the lookup is assumed to overlap with the frontend latency of
162     # the crossbar
163     snoop_filter = SnoopFilter(lookup_latency = 0)
164 
165     # This specialisation of the coherent crossbar is to be considered
166     # the point of unification, it connects the dcache and the icache
167     # to the first level of unified cache.
168     point_of_unification = True
169 
170 # One of the key coherent crossbar instances is the system
171 # interconnect, tying together the CPU clusters, GPUs, and any I/O
172 # coherent requestors, and DRAM controllers.
173 class SystemXBar(CoherentXBar):
174     # 128-bit crossbar by default
175     width = 16
176 
177     # A handful pipeline stages for each portion of the latency
178     # contributions.
179     frontend_latency = 3
180     forward_latency = 4
181     response_latency = 2
182     snoop_response_latency = 4
183 
184     # Use a snoop-filter by default
185     snoop_filter = SnoopFilter(lookup_latency = 1)
186 
187     # This specialisation of the coherent crossbar is to be considered
188     # the point of coherency, as there are no (coherent) downstream
189     # caches.
190     point_of_coherency = True
191 
192     # This specialisation of the coherent crossbar is to be considered
193     # the point of unification, it connects the dcache and the icache
194     # to the first level of unified cache. This is needed for systems
195     # without caches where the SystemXBar is also the point of
196     # unification.
197     point_of_unification = True
```

On the above code, there are two implmenetations for the XBar. 
One is the L2Xbar connecting L2 cache and L3 cache.
The other is the SystemXBar connecting the L3 cache and the memory.


```python
148 class L3Cache(Cache):
149     """Simple L3 Cache bank with default values
150        This assumes that the L3 is made up of multiple banks. This cannot
151        be used as a standalone L3 cache.
152     """
153 
154     # Default parameters
155     assoc = 32
156     tag_latency = 40
157     data_latency = 40
158     response_latency = 10
159     mshrs = 256
160     tgts_per_mshr = 12
161     clusivity = 'mostly_excl'
162 
163     size = '4MB'
164 
165     def __init__(self):
166         super(L3Cache, self).__init__()
167 
168     def connectCPUSideBus(self, bus):
169         self.cpu_side = bus.master
170 
171     def connectMemSideBus(self, bus):
172         self.mem_side = bus.slave
173 
```

To connect the L3cache with the system memory through the SystemXBar,
L3Cache python class provides connectXXXSideBus interface functions.
It just allocates the proper parameter of the 
bus's ports to the corredponding ports of the L3Cache. 
When you look up the python script defining all the parameters
required for initiating L3cache and the XBar, 
you can understand whar are those ports in the above 
configuration script. 

```cpp
 75 class BaseCache(ClockedObject):
 76     type = 'BaseCache'
......
113     cpu_side = SlavePort("Upstream port closer to the CPU and/or device")
114     mem_side = MasterPort("Downstream port closer to memory")
```

```cpp
 49 class BaseXBar(ClockedObject):
 50     type = 'BaseXBar'
 51     abstract = True
 52     cxx_header = "mem/xbar.hh"
 53 
 54     slave = VectorSlavePort("Vector port for connecting masters")
 55     master = VectorMasterPort("Vector port for connecting slaves")
```

Yeah two classes have different names for ports
connecting different sides of the modules 
to the other components. 
When the connectMemSideBus function is invoked of the L3 cache, 
the mem_side of the L3 cache is attached to the slave part of the XBar.
The slave of the XBar is the CpuSidePort of the XBar.
Therefore, the slave port is used to receive packets 
sent from the connected cache.
On the other hand,
the master port is used to send packets from the 
XBar to the connected memory ports. 
Therefore, it is a memSidePort. 
The name of the ports are slightly confusing 
it is very similar of those cpuSide and memSide things.

## Receiving packets from the caches
### Initializing CoherentXBar

```cpp
  58 CoherentXBar::CoherentXBar(const CoherentXBarParams &p)
  59     : BaseXBar(p), system(p.system), snoopFilter(p.snoop_filter),
  60       snoopResponseLatency(p.snoop_response_latency),
  61       maxOutstandingSnoopCheck(p.max_outstanding_snoops),
  62       maxRoutingTableSizeCheck(p.max_routing_table_size),
  63       pointOfCoherency(p.point_of_coherency),
  64       pointOfUnification(p.point_of_unification),
  65 
  66       ADD_STAT(snoops, statistics::units::Count::get(), "Total snoops"),
  67       ADD_STAT(snoopTraffic, statistics::units::Byte::get(), "Total snoop traffic"),
  68       ADD_STAT(snoopFanout, statistics::units::Count::get(),
  69                "Request fanout histogram")
  70 {
  71     // create the ports based on the size of the memory-side port and
  72     // CPU-side port vector ports, and the presence of the default port,
  73     // the ports are enumerated starting from zero
  74     for (int i = 0; i < p.port_mem_side_ports_connection_count; ++i) {
  75         std::string portName = csprintf("%s.mem_side_port[%d]", name(), i);
  76         RequestPort* bp = new CoherentXBarRequestPort(portName, *this, i);
  77         memSidePorts.push_back(bp);
  78         reqLayers.push_back(new ReqLayer(*bp, *this,
  79                                          csprintf("reqLayer%d", i)));
  80         snoopLayers.push_back(
  81                 new SnoopRespLayer(*bp, *this, csprintf("snoopLayer%d", i)));
  82     }
  83 
  84     // see if we have a default CPU-side-port device connected and if so add
  85     // our corresponding memory-side port
  86     if (p.port_default_connection_count) {
  87         defaultPortID = memSidePorts.size();
  88         std::string portName = name() + ".default";
  89         RequestPort* bp = new CoherentXBarRequestPort(portName, *this,
  90                                                     defaultPortID);
  91         memSidePorts.push_back(bp);
  92         reqLayers.push_back(new ReqLayer(*bp, *this, csprintf("reqLayer%d",
  93                                          defaultPortID)));
  94         snoopLayers.push_back(new SnoopRespLayer(*bp, *this,
  95                                                  csprintf("snoopLayer%d",
  96                                                           defaultPortID)));
  97     }
  98 
  99     // create the CPU-side ports, once again starting at zero
 100     for (int i = 0; i < p.port_cpu_side_ports_connection_count; ++i) {
 101         std::string portName = csprintf("%s.cpu_side_port[%d]", name(), i);
 102         QueuedResponsePort* bp = new CoherentXBarResponsePort(portName,
 103                                                             *this, i);
 104         cpuSidePorts.push_back(bp);
 105         respLayers.push_back(new RespLayer(*bp, *this,
 106                                            csprintf("respLayer%d", i)));
 107         snoopRespPorts.push_back(new SnoopRespPort(*bp, *this));
 108     }
 109 }
```

To understand how the ports in the CoherentXBar works,
we need to see the constructor of it 
because it populates the port and assigns the generated ports 
to the proper data structures of the CoherentXBar. 
Because the one CoherentXBar can be connected to multiple entires 
in both CpuSide and MemSide, 
it can have multiple ports. 

The p.port_XXX_side_ports_connection_count parameter
determines how many ports should be assigned to the 
XBar (line 74-82 for sending ports and 99-108 for receiving ports).
Also note that it generates matching layers 
based on the types of the ports.
SnoopRespLayer is also generated per sending port
connected to the memory side. 

For the receiving ports, it generates the RespLayers 
and pushes the generated layers to the respLayers memeber field.
Also, it generates RequestLayers
Therefore, it generates proper number of ports 
in its constructor and push them 
to the proper member fields, cpuSidePorts and memSidePorts. 
Instead of the SnoopRespLayer it generates SnnopRespPort 
per receiving ports connected to the cache. 

## recvTimingReq
```cpp
 88     class CoherentXBarResponsePort : public QueuedResponsePort
 89     {
......
109         bool
110         recvTimingReq(PacketPtr pkt) override
111         {
112             return xbar.recvTimingReq(pkt, id);
113         }
```
Whenever the cache connected to the XBar sends the packet 
through the connected memSidePort,
it invokes the recvTimingReq function of the CoherentXBarResponsePort.
This function just redirects the request to the 
recvtTimingReq of the XBar.

```cpp
 148 bool
 149 CoherentXBar::recvTimingReq(PacketPtr pkt, PortID cpu_side_port_id)
 150 {
 151     // determine the source port based on the id
 152     ResponsePort *src_port = cpuSidePorts[cpu_side_port_id];
 153 
 154     // remember if the packet is an express snoop
 155     bool is_express_snoop = pkt->isExpressSnoop();
 156     bool cache_responding = pkt->cacheResponding();
 157     // for normal requests, going downstream, the express snoop flag
 158     // and the cache responding flag should always be the same
 159     assert(is_express_snoop == cache_responding);
 160 
 161     // determine the destination based on the destination address range
 162     PortID mem_side_port_id = findPort(pkt->getAddrRange());
 163 
 164     // test if the crossbar should be considered occupied for the current
 165     // port, and exclude express snoops from the check
 166     if (!is_express_snoop &&
 167         !reqLayers[mem_side_port_id]->tryTiming(src_port)) {
 168         DPRINTF(CoherentXBar, "%s: src %s packet %s BUSY\n", __func__,
 169                 src_port->name(), pkt->print());
 170         return false;
 171     }
 172 
 173     DPRINTF(CoherentXBar, "%s: src %s packet %s\n", __func__,
 174             src_port->name(), pkt->print());
```

### Snoop flags required to understand XBar
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
```
The cacheResponding flag means that 
it has responsibility of updating current 
block of the cache because it has 
modified the block with write operation.
Therefore, when this flag is not set,
Also, it should be considered together with the hasSharers flag.
When the hasSharers flag is set, 
it measn that current block is shared with other processors.
Therefore, the cacheResponding flag doesn't 
mean anything when it has sharers. 


```cpp
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
```


```cpp
 676     /**
 677      * The express snoop flag is used for two purposes. Firstly, it is
 678      * used to bypass flow control for normal (non-snoop) requests
 679      * going downstream in the memory system. In cases where a cache
 680      * is responding to a snoop from another cache (it had a dirty
 681      * line), but the line is not writable (and there are possibly
 682      * other copies), the express snoop flag is set by the downstream
 683      * cache to invalidate all other copies in zero time. Secondly,
 684      * the express snoop flag is also set to be able to distinguish
 685      * snoop packets that came from a downstream cache, rather than
 686      * snoop packets from neighbouring caches.
 687      */
```

### finding port and checking its availability
After checking the condition of the packet, 
it first need to retrieve the port that the packet should be 
delivered to. 
Based on the address requested by the cpuSide component, 
the memSidePort will be determined. 

```cpp
330 PortID
331 BaseXBar::findPort(AddrRange addr_range)
332 {
333     // we should never see any address lookups before we've got the
334     // ranges of all connected CPU-side-port modules
335     assert(gotAllAddrRanges);
336     
337     // Check the address map interval tree
338     auto i = portMap.contains(addr_range);
339     if (i != portMap.end()) {
340         return i->second;
341     }
342 
343     // Check if this matches the default range
344     if (useDefaultRange) {
345         if (addr_range.isSubset(defaultRange)) {
346             DPRINTF(AddrRanges, "  found addr %s on default\n",
347                     addr_range.to_string());
348             return defaultPortID;
349         }
350     } else if (defaultPortID != InvalidPortID) {
351         DPRINTF(AddrRanges, "Unable to find destination for %s, "
352                 "will use default port\n", addr_range.to_string());
353         return defaultPortID;
354     }
355 
356     // we should use the range for the default port and it did not
357     // match, or the default port is not set
358     fatal("Unable to find destination for %s on %s\n", addr_range.to_string(),
359           name());
360 }
```

findPort function searches portMap and return 
the number of memSidePort.
You might remember the each port is 
managed by the layer in the XBar.
Therefore, to check its availability,
we need to invoke the tryTiming function of the 
request layer associated with the found port number. 

```cpp
181 template <typename SrcType, typename DstType>
182 bool
183 BaseXBar::Layer<SrcType, DstType>::tryTiming(SrcType* src_port)
184 {
185     // if we are in the retry state, we will not see anything but the
186     // retrying port (or in the case of the snoop ports the snoop
187     // response port that mirrors the actual CPU-side port) as we leave
188     // this state again in zero time if the peer does not immediately
189     // call the layer when receiving the retry
190 
191     // first we see if the layer is busy, next we check if the
192     // destination port is already engaged in a transaction waiting
193     // for a retry from the peer
194     if (state == BUSY || waitingForPeer != NULL) {
195         // the port should not be waiting already
196         assert(std::find(waitingForLayer.begin(), waitingForLayer.end(),
197                          src_port) == waitingForLayer.end());
198 
199         // put the port at the end of the retry list waiting for the
200         // layer to be freed up (and in the case of a busy peer, for
201         // that transaction to go through, and then the layer to free
202         // up)
203         waitingForLayer.push_back(src_port);
204         return false;
205     }
206 
207     state = BUSY;
208 
209     return true;
210 }
```

## Handling snoop request in the recvTimingReq 
```cpp
 176     // store size and command as they might be modified when
 177     // forwarding the packet
 178     unsigned int pkt_size = pkt->hasData() ? pkt->getSize() : 0;
 179     unsigned int pkt_cmd = pkt->cmdToIndex();
 180 
 181     // store the old header delay so we can restore it if needed
 182     Tick old_header_delay = pkt->headerDelay;
 183 
 184     // a request sees the frontend and forward latency
 185     Tick xbar_delay = (frontendLatency + forwardLatency) * clockPeriod();
 186 
 187     // set the packet header and payload delay
 188     calcPacketTiming(pkt, xbar_delay);
 189 
 190     // determine how long to be crossbar layer is busy
 191     Tick packetFinishTime = clockEdge(headerLatency) + pkt->payloadDelay;
 192 
 193     // is this the destination point for this packet? (e.g. true if
 194     // this xbar is the PoC for a cache maintenance operation to the
 195     // PoC) otherwise the destination is any cache that can satisfy
 196     // the request
 197     const bool is_destination = isDestination(pkt);
 198 
 199     const bool snoop_caches = !system->bypassCaches() &&
 200         pkt->cmd != MemCmd::WriteClean;
 ```
First of all, it inspects packet to figure out 
where is the destination of the packet.

```cpp
414     bool    
415     isDestination(const PacketPtr pkt) const        
416     {       
417         return (pkt->req->isToPOC() && pointOfCoherency) ||
418             (pkt->req->isToPOU() && pointOfUnification);
419     }
```

When you look up the implementation of the isDestination function,
it compares the packet's isToPOC and isToPOU with pointOfCoherency and pointOfUnification, respectively.
The pointOfXXX is the member field of the XBar and initialized with 
parameters passed from the configuration script.
Based on the where the XBar is located,
for example, in between the L2 cache and L3 cache 
or L3 cache and external memories,
either of those flags can be set. 
The PoU for a core is the point at which the instruction and data caches and translation table walks of the core are guaranteed to see the same copy of a memory location.
For a particular address, the PoC is the point at which all observers, for example, cores, DSPs, or DMA engines, that can access memory, are guaranteed to see the same copy of a memory location.
Also, it checks whether the current packet should be 
checked regarding the snoop.
Note that the WriteClean event means that writes dirty data below without evicting. 
\XXX{This type of packet is usually generated when the cache block 
is evicted without any modification until its eviction.}
Most of the time the cache should not be bypassed 
and the packet command is not the WriteClean,
the below condition should be executed. 


```cpp
 201     if (snoop_caches) {
 202         assert(pkt->snoopDelay == 0);
 203 
 204         if (pkt->isClean() && !is_destination) {
 205             // before snooping we need to make sure that the memory
 206             // below is not busy and the cache clean request can be
 207             // forwarded to it
 208             if (!memSidePorts[mem_side_port_id]->tryTiming(pkt)) {
 209                 DPRINTF(CoherentXBar, "%s: src %s packet %s RETRY\n", __func__,
 210                         src_port->name(), pkt->print());
 211 
 212                 // update the layer state and schedule an idle event
 213                 reqLayers[mem_side_port_id]->failedTiming(src_port,
 214                                                         clockEdge(Cycles(1)));
 215                 return false;
 216             }
 217         }
 218 
 219 
 220         // the packet is a memory-mapped request and should be
 221         // broadcasted to our snoopers but the source
 222         if (snoopFilter) {
 223             // check with the snoop filter where to forward this packet
 224             auto sf_res = snoopFilter->lookupRequest(pkt, *src_port);
 225             // the time required by a packet to be delivered through
 226             // the xbar has to be charged also with to lookup latency
 227             // of the snoop filter
 228             pkt->headerDelay += sf_res.second * clockPeriod();
 229             DPRINTF(CoherentXBar, "%s: src %s packet %s SF size: %i lat: %i\n",
 230                     __func__, src_port->name(), pkt->print(),
 231                     sf_res.first.size(), sf_res.second);
 232 
 233             if (pkt->isEviction()) {
 234                 // for block-evicting packets, i.e. writebacks and
 235                 // clean evictions, there is no need to snoop up, as
 236                 // all we do is determine if the block is cached or
 237                 // not, instead just set it here based on the snoop
 238                 // filter result
 239                 if (!sf_res.first.empty())
 240                     pkt->setBlockCached();
 241             } else {
 242                 forwardTiming(pkt, cpu_side_port_id, sf_res.first);
 243             }
 244         } else {
 245             forwardTiming(pkt, cpu_side_port_id);
 246         }
 247 
 248         // add the snoop delay to our header delay, and then reset it
 249         pkt->headerDelay += pkt->snoopDelay;
 250         pkt->snoopDelay = 0;
 251     }
```

### Forward snooping requests 
```cpp
307     /**
308      * Forward a timing packet to our snoopers, potentially excluding
309      * one of the connected coherent requestors to avoid sending a packet
310      * back to where it came from.
311      *
312      * @param pkt Packet to forward
313      * @param exclude_cpu_side_port_id Id of CPU-side port to exclude
314      */
315     void
316     forwardTiming(PacketPtr pkt, PortID exclude_cpu_side_port_id)
317     {
318         forwardTiming(pkt, exclude_cpu_side_port_id, snoopPorts);
319     }
```

```cpp
 123 void
 124 CoherentXBar::init()
 125 {
 126     BaseXBar::init();
 127 
 128     // iterate over our CPU-side ports and determine which of our
 129     // neighbouring memory-side ports are snooping and add them as snoopers
 130     for (const auto& p: cpuSidePorts) {
 131         // check if the connected memory-side port is snooping
 132         if (p->isSnooping()) {
 133             DPRINTF(AddrRanges, "Adding snooping requestor %s\n",
 134                     p->getPeer());
 135             snoopPorts.push_back(p);
 136         }
 137     }
 138 
 139     if (snoopPorts.empty())
 140         warn("CoherentXBar %s has no snooping ports attached!\n", name());
 141 
 142     // inform the snoop filter about the CPU-side ports so it can create
 143     // its own internal representation
 144     if (snoopFilter)
 145         snoopFilter->setCPUSidePorts(cpuSidePorts);
 146 }
```

For the forwardTiming, when it doesn't have a vector 
containing all the destination ports to send the snoop requests,
it sends the request to the snoopPorts 
populated at its initialization function. 

```cpp
 699 void
 700 CoherentXBar::forwardTiming(PacketPtr pkt, PortID exclude_cpu_side_port_id,
 701                            const std::vector<QueuedResponsePort*>& dests)
 702 {
 703     DPRINTF(CoherentXBar, "%s for %s\n", __func__, pkt->print());
 704 
 705     // snoops should only happen if the system isn't bypassing caches
 706     assert(!system->bypassCaches());
 707 
 708     unsigned fanout = 0;
 709 
 710     for (const auto& p: dests) {
 711         // we could have gotten this request from a snooping requestor
 712         // (corresponding to our own CPU-side port that is also in
 713         // snoopPorts) and should not send it back to where it came
 714         // from
 715         if (exclude_cpu_side_port_id == InvalidPortID ||
 716             p->getId() != exclude_cpu_side_port_id) {
 717             // cache is not allowed to refuse snoop
 718             p->sendTimingSnoopReq(pkt);
 719             fanout++;
 720         }
 721     }
 722 
 723     // Stats for fanout of this forward operation
 724     snoopFanout.sample(fanout);
 725 }
```

The forwardTiming functions sends the snooping request 
to the other components connected to the XBar
except the one that is currently receiving the packet 
from the cache side. 
Note that it traverse all destination ports 
passed to the function and invokes sendTimingSnoopReq function.
However, note that it excludes the one 
specified as exclude_cpu_side_port_id. 
This one mostly is the port initially received the 
cache snoop packet. 


## Sink packet or forward packet to the next level 
```cpp
 252 
 253     // set up a sensible starting point
 254     bool success = true;
 255 
 256     // remember if the packet will generate a snoop response by
 257     // checking if a cache set the cacheResponding flag during the
 258     // snooping above
 259     const bool expect_snoop_resp = !cache_responding && pkt->cacheResponding();
 260     bool expect_response = pkt->needsResponse() && !pkt->cacheResponding();
 261 
 262     const bool sink_packet = sinkPacket(pkt);
 263 
 264     // in certain cases the crossbar is responsible for responding
 265     bool respond_directly = false;
 266     // store the original address as an address mapper could possibly
 267     // modify the address upon a sendTimingRequest
 268     const Addr addr(pkt->getAddr());
 269     if (sink_packet) {
 270         DPRINTF(CoherentXBar, "%s: Not forwarding %s\n", __func__,
 271                 pkt->print());
 272     } else {
 273         // determine if we are forwarding the packet, or responding to
 274         // it
 275         if (forwardPacket(pkt)) {
 276             // if we are passing on, rather than sinking, a packet to
 277             // which an upstream cache has committed to responding,
 278             // the line was needs writable, and the responding only
 279             // had an Owned copy, so we need to immidiately let the
 280             // downstream caches know, bypass any flow control
 281             if (pkt->cacheResponding()) {
 282                 pkt->setExpressSnoop();
 283             }
 284 
 285             // make sure that the write request (e.g., WriteClean)
 286             // will stop at the memory below if this crossbar is its
 287             // destination
 288             if (pkt->isWrite() && is_destination) {
 289                 pkt->clearWriteThrough();
 290             }
 291 
 292             // since it is a normal request, attempt to send the packet
 293             success = memSidePorts[mem_side_port_id]->sendTimingReq(pkt);
 294         } else {
 295             // no need to forward, turn this packet around and respond
 296             // directly
 297             assert(pkt->needsResponse());
 298 
 299             respond_directly = true;
 300             assert(!expect_snoop_resp);
 301             expect_response = false;
 302         }
 303     }
 304 
 ```

### Check packet's flags to figure out next step 
```cpp
1079 bool
1080 CoherentXBar::sinkPacket(const PacketPtr pkt) const
1081 {
1082     // we can sink the packet if:
1083     // 1) the crossbar is the point of coherency, and a cache is
1084     //    responding after being snooped
1085     // 2) the crossbar is the point of coherency, and the packet is a
1086     //    coherency packet (not a read or a write) that does not
1087     //    require a response
1088     // 3) this is a clean evict or clean writeback, but the packet is
1089     //    found in a cache above this crossbar
1090     // 4) a cache is responding after being snooped, and the packet
1091     //    either does not need the block to be writable, or the cache
1092     //    that has promised to respond (setting the cache responding
1093     //    flag) is providing writable and thus had a Modified block,
1094     //    and no further action is needed
1095     return (pointOfCoherency && pkt->cacheResponding()) ||
1096         (pointOfCoherency && !(pkt->isRead() || pkt->isWrite()) &&
1097          !pkt->needsResponse()) ||
1098         (pkt->isCleanEviction() && pkt->isBlockCached()) ||
1099         (pkt->cacheResponding() &&
1100          (!pkt->needsWritable() || pkt->responderHadWritable()));
1101 }
1102 
1103 bool
1104 CoherentXBar::forwardPacket(const PacketPtr pkt)
1105 {
1106     // we are forwarding the packet if:
1107     // 1) this is a cache clean request to the PoU/PoC and this
1108     //    crossbar is above the PoU/PoC
1109     // 2) this is a read or a write
1110     // 3) this crossbar is above the point of coherency
1111     if (pkt->isClean()) {
1112         return !isDestination(pkt);
1113     }
1114     return pkt->isRead() || pkt->isWrite() || !pointOfCoherency;
1115 }

```

 ```cpp
 305     if (snoopFilter && snoop_caches) {
 306         // Let the snoop filter know about the success of the send operation
 307         snoopFilter->finishRequest(!success, addr, pkt->isSecure());
 308     }
 309 
 310     // check if we were successful in sending the packet onwards
 311     if (!success)  {
 312         // express snoops should never be forced to retry
 313         assert(!is_express_snoop);
 314 
 315         // restore the header delay
 316         pkt->headerDelay = old_header_delay;
 317 
 318         DPRINTF(CoherentXBar, "%s: src %s packet %s RETRY\n", __func__,
 319                 src_port->name(), pkt->print());
 320 
 321         // update the layer state and schedule an idle event
 322         reqLayers[mem_side_port_id]->failedTiming(src_port,
 323                                                 clockEdge(Cycles(1)));
 324     } else {
 325         // express snoops currently bypass the crossbar state entirely
 326         if (!is_express_snoop) {
 327             // if this particular request will generate a snoop
 328             // response
 329             if (expect_snoop_resp) {
 330                 // we should never have an exsiting request outstanding
 331                 assert(outstandingSnoop.find(pkt->req) ==
 332                        outstandingSnoop.end());
 333                 outstandingSnoop.insert(pkt->req);
 334 
 335                 // basic sanity check on the outstanding snoops
 336                 panic_if(outstandingSnoop.size() > maxOutstandingSnoopCheck,
 337                          "%s: Outstanding snoop requests exceeded %d\n",
 338                          name(), maxOutstandingSnoopCheck);
 339             }
 340 
 341             // remember where to route the normal response to
 342             if (expect_response || expect_snoop_resp) {
 343                 assert(routeTo.find(pkt->req) == routeTo.end());
 344                 routeTo[pkt->req] = cpu_side_port_id;
 345 
 346                 panic_if(routeTo.size() > maxRoutingTableSizeCheck,
 347                          "%s: Routing table exceeds %d packets\n",
 348                          name(), maxRoutingTableSizeCheck);
 349             }
 350 
 351             // update the layer state and schedule an idle event
 352             reqLayers[mem_side_port_id]->succeededTiming(packetFinishTime);
 353         }
 354 
 355         // stats updates only consider packets that were successfully sent
 356         pktCount[cpu_side_port_id][mem_side_port_id]++;
 357         pktSize[cpu_side_port_id][mem_side_port_id] += pkt_size;
 358         transDist[pkt_cmd]++;
 359 
 360         if (is_express_snoop) {
 361             snoops++;
 362             snoopTraffic += pkt_size;
 363         }
 364     }
 365 
 366     if (sink_packet)
 367         // queue the packet for deletion
 368         pendingDelete.reset(pkt);
 369 
 370     // normally we respond to the packet we just received if we need to
 371     PacketPtr rsp_pkt = pkt;
 372     PortID rsp_port_id = cpu_side_port_id;
 373 
 374     // If this is the destination of the cache clean operation the
 375     // crossbar is responsible for responding. This crossbar will
 376     // respond when the cache clean is complete. A cache clean
 377     // is complete either:
 378     // * direcly, if no cache above had a dirty copy of the block
 379     //   as indicated by the satisfied flag of the packet, or
 380     // * when the crossbar has seen both the cache clean request
 381     //   (CleanSharedReq, CleanInvalidReq) and the corresponding
 382     //   write (WriteClean) which updates the block in the memory
 383     //   below.
 384     if (success &&
 385         ((pkt->isClean() && pkt->satisfied()) ||
 386          pkt->cmd == MemCmd::WriteClean) &&
 387         is_destination) {
 388         PacketPtr deferred_rsp = pkt->isWrite() ? nullptr : pkt;
 389         auto cmo_lookup = outstandingCMO.find(pkt->id);
 390         if (cmo_lookup != outstandingCMO.end()) {
 391             // the cache clean request has already reached this xbar
 392             respond_directly = true;
 393             if (pkt->isWrite()) {
 394                 rsp_pkt = cmo_lookup->second;
 395                 assert(rsp_pkt);
 396 
 397                 // determine the destination
 398                 const auto route_lookup = routeTo.find(rsp_pkt->req);
 399                 assert(route_lookup != routeTo.end());
 400                 rsp_port_id = route_lookup->second;
 401                 assert(rsp_port_id != InvalidPortID);
 402                 assert(rsp_port_id < respLayers.size());
 403                 // remove the request from the routing table
 404                 routeTo.erase(route_lookup);
 405             }
 406             outstandingCMO.erase(cmo_lookup);
 407         } else {
 408             respond_directly = false;
 409             outstandingCMO.emplace(pkt->id, deferred_rsp);
 410             if (!pkt->isWrite()) {
 411                 assert(routeTo.find(pkt->req) == routeTo.end());
 412                 routeTo[pkt->req] = cpu_side_port_id;
 413 
 414                 panic_if(routeTo.size() > maxRoutingTableSizeCheck,
 415                          "%s: Routing table exceeds %d packets\n",
 416                          name(), maxRoutingTableSizeCheck);
 417             }
 418         }
 419     }
 420 
 421 
 422     if (respond_directly) {
 423         assert(rsp_pkt->needsResponse());
 424         assert(success);
 425 
 426         rsp_pkt->makeResponse();
 427 
 428         if (snoopFilter && !system->bypassCaches()) {
 429             // let the snoop filter inspect the response and update its state
 430             snoopFilter->updateResponse(rsp_pkt, *cpuSidePorts[rsp_port_id]);
 431         }
 432 
 433         // we send the response after the current packet, even if the
 434         // response is not for this packet (e.g. cache clean operation
 435         // where both the request and the write packet have to cross
 436         // the destination xbar before the response is sent.)
 437         Tick response_time = clockEdge() + pkt->headerDelay;
 438         rsp_pkt->headerDelay = 0;
 439 
 440         cpuSidePorts[rsp_port_id]->schedTimingResp(rsp_pkt, response_time);
 441     }
 442 
 443     return success;
 444 }




```

## Sending packets to the memory






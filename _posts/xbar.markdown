
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


### Connecting ports
```cpp
 87 Port &
 88 BaseXBar::getPort(const std::string &if_name, PortID idx)
 89 {
 90     if (if_name == "mem_side_ports" && idx < memSidePorts.size()) {
 91         // the memory-side ports index translates directly to the vector
 92         // position
 93         return *memSidePorts[idx];
 94     } else  if (if_name == "default") {
 95         return *memSidePorts[defaultPortID];
 96     } else if (if_name == "cpu_side_ports" && idx < cpuSidePorts.size()) {
 97         // the CPU-side ports index translates directly to the vector position
 98         return *cpuSidePorts[idx];
 99     } else {
100         return ClockedObject::getPort(if_name, idx);
101     }
102 }
```

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

# How to initiate TDX through QEMU command

QEMU provides macro function **OBJECT_DEFINE_TYPE_WITH_INTERFACES** to introduce
new QOM.
```cpp
#define OBJECT_DEFINE_TYPE_WITH_INTERFACES(ModuleObjName, module_obj_name, \
                                           MODULE_OBJ_NAME, \
                                           PARENT_MODULE_OBJ_NAME, ...) \
    OBJECT_DEFINE_TYPE_EXTENDED(ModuleObjName, module_obj_name, \
                                MODULE_OBJ_NAME, PARENT_MODULE_OBJ_NAME, \
                                false, __VA_ARGS__)
```

```cpp
#define OBJECT_DEFINE_TYPE_EXTENDED(ModuleObjName, module_obj_name, \
                                    MODULE_OBJ_NAME, PARENT_MODULE_OBJ_NAME, \
                                    ABSTRACT, ...) \
    static void \
    module_obj_name##_finalize(Object *obj); \
    static void \
    module_obj_name##_class_init(ObjectClass *oc, void *data); \
    static void \
    module_obj_name##_init(Object *obj); \
    \
    static const TypeInfo module_obj_name##_info = { \
        .parent = TYPE_##PARENT_MODULE_OBJ_NAME, \
        .name = TYPE_##MODULE_OBJ_NAME, \
        .instance_size = sizeof(ModuleObjName), \
        .instance_align = __alignof__(ModuleObjName), \
        .instance_init = module_obj_name##_init, \
        .instance_finalize = module_obj_name##_finalize, \
        .class_size = sizeof(ModuleObjName##Class), \
        .class_init = module_obj_name##_class_init, \
        .abstract = ABSTRACT, \
        .interfaces = (InterfaceInfo[]) { __VA_ARGS__ } , \
    }; \
    \
    static void \
    module_obj_name##_register_types(void) \
    { \
        type_register_static(&module_obj_name##_info); \
    } \
    type_init(module_obj_name##_register_types);
```

## Define tdx-guest type object 
```cpp
 971 /* tdx guest */
 972 OBJECT_DEFINE_TYPE_WITH_INTERFACES(TdxGuest,
 973                                    tdx_guest,
 974                                    TDX_GUEST,
 975                                    CONFIDENTIAL_GUEST_SUPPORT,
 976                                    { TYPE_USER_CREATABLE },
 977                                    { NULL })
```


It makes the mapping from QEMU command to QOM object. Here when tdx-guest QEMU 
object command is passed, it instantiate the structure called TdxGuest 
initialized with some optional parameters of the tdx-guest QEMU object. 


```cpp
 44 #define TYPE_TDX_GUEST "tdx-guest"
 45 #define TDX_GUEST(obj)     \
 46     OBJECT_CHECK(TdxGuest, (obj), TYPE_TDX_GUEST)
 47
 48 typedef struct TdxGuestClass {
 49     ConfidentialGuestSupportClass parent_class;
 50 } TdxGuestClass;
 51
 52 typedef struct TdxGuest {
 53     ConfidentialGuestSupport parent_obj;
 54
 55     QemuMutex lock;
 56
 57     bool initialized;
 58     bool debug;
 59     bool sept_ve_disable;
 60     uint8_t mrconfigid[48];     /* sha348 digest */
 61     uint8_t mrowner[48];        /* sha348 digest */
 62     uint8_t mrownerconfig[48];  /* sha348 digest */
 63
 64     TdxFirmware fw;
 65
 66     /* runtime state */
 67     int event_notify_interrupt;
 68
 69     /* GetQuote */
 70     int quote_generation_num;
 71     char *quote_generation_str;
 72     SocketAddress *quote_generation;
 73 } TdxGuest;
```

As shown in the macro, QEMU needs to define the actual object, defined as struct
TdxGuest in the above code, to be initialized when the QEMU parameter is passed. 
Here the object name is **TdxGuest**. Note that the macro utilize TdxGuest, to 
define and initialize the tdx_guest_info TypeInfo. 

## Generate tdx-guest type object through command line
### Define parameters and init function for instantiating tdx-guest
QEMU first need to be informed that which parameters are required to initialize
QOM object through command line. QEMU provide proper set of interface functions 
called **object_property_add_\*** to add parameters of particular type.

```cpp
 979 static void tdx_guest_init(Object *obj)
 980 {
 981     TdxGuest *tdx = TDX_GUEST(obj);
 982 
 983     qemu_mutex_init(&tdx->lock);
 984 
 985     /* TODO: set only if user doens't specify reboot action */
 986     reboot_action = REBOOT_ACTION_SHUTDOWN;
 987 
 988     tdx->debug = false;
 989     tdx->sept_ve_disable = false;
 990     object_property_add_bool(obj, "debug", tdx_guest_get_debug,
 991                              tdx_guest_set_debug);
 992     object_property_add_bool(obj, "sept-ve-disable",
 993                              tdx_guest_get_sept_ve_disable,
 994                              tdx_guest_set_sept_ve_disable);
 995     object_property_add_sha384(obj, "mrconfigid", tdx->mrconfigid,
 996                                OBJ_PROP_FLAG_READWRITE);
 997     object_property_add_sha384(obj, "mrowner", tdx->mrowner,
 998                                OBJ_PROP_FLAG_READWRITE);
 999     object_property_add_sha384(obj, "mrownerconfig", tdx->mrownerconfig,
1000                                OBJ_PROP_FLAG_READWRITE);
1001 
1002     tdx->quote_generation_str = NULL;
1003     tdx->quote_generation = NULL;
1004     object_property_add_str(obj, "quote-generation-service",
1005                             tdx_guest_get_quote_generation,
1006                             tdx_guest_set_quote_generation);
1007 
1008     tdx->event_notify_interrupt = -1;
1009 }
```

Based on the information QEMU automatically generates information regarding 
**tdx-guest** QOM, which is shown in the below code. 

```cpp
 814 ##
 815 # @TdxGuestProperties:
 816 #
 817 # Properties for sev-guest objects.
 818 #
 819 # @debug: enable debug mode (default: off)
 820 #
 821 # @mrconfigid: MRCONFIGID SHA384 hex string of 48 * 2 length (default: 0)
 822 #
 823 # @mrowner: MROWNER SHA384 hex string of 48 * 2 length (default: 0)
 824 #
 825 # @mrownerconfig: MROWNERCONFIG SHA384 hex string of 48 * 2 length (default: 0)
 826 #
 827 # @quote-generation-service: socket address for Quote Generation Service(QGS)
 828 #
 829 # Since: 6.0
 830 ##
 831 { 'struct': 'TdxGuestProperties',
 832   'data': { '*debug': 'bool',
 833             '*sept-ve-disable': 'bool',
 834             '*mrconfigid': 'str',
 835             '*mrowner': 'str',
 836             '*mrownerconfig': 'str',
 837             '*quote-generation-service': 'str' } }
```

## Pass the generated tdx-guest object to memory-encryption 
QEMU already defines the interface called **memory-encryption** to handle the 
secure VM functionalities such as AMD SEV. Therefore TDX also utilize the same 
interface and pass the initialized **tdx-guest** QOM so that **ms->cgs** can 
point to this tdx object. 

**hw/core/machine.c**
```cpp
 865     /* For compatibility */
 866     object_class_property_add_str(oc, "memory-encryption",
 867         machine_get_memory_encryption, machine_set_memory_encryption);
 868     object_class_property_set_description(oc, "memory-encryption",
 869         "Set memory encryption object to use");

```

```cpp
 456 static char *machine_get_memory_encryption(Object *obj, Error **errp)
 457 {
 458     MachineState *ms = MACHINE(obj);
 459 
 460     if (ms->cgs) {
 461         return g_strdup(object_get_canonical_path_component(OBJECT(ms->cgs)));
 462     }
 463 
 464     return NULL;
 465 }
 466
 467 static void machine_set_memory_encryption(Object *obj, const char *value,
 468                                         Error **errp)
 469 {
 470     Object *cgs =
 471         object_resolve_path_component(object_get_objects_root(), value);
 472 
 473     if (!cgs) {               
 474         error_setg(errp, "No such memory encryption object '%s'", value);
 475         return;
 476     }
 477 
 478     object_property_set_link(obj, "confidential-guest-support", cgs, errp);
 479 }
```

XXX: I don't know when the machine_set_memory_encryption function is invoked and
assign the passed object to the ms->cgs.

## Reference TDX object (TdxGuest) in the QEMU code 
To convert the cgs object to the TDX object, it invokes **TDX_GUEST** macro 
function.


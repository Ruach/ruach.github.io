---
layout: post
titile: "Linux usb core driver interface
categories: linux, embedded-linux
---
# USB drivers are designed for interfaces

For USB device,
the drivers are not designed for the USB device itself,
but for its interfaces that supported by the USB devices. 
Therefore, when a new USB device is plugged in to the usb-bus,
the first thing needs to done by the usb core system is 
enumerating configuration, interfaces, and endponints 
supported by the plugged device.

However, 
in the Linux usb-subsystem, 
whether it is a physical usb device or its interfaces,
they are all handles as a usb device
and processed by a single unified APIs to register the devices.  

In this posting,
we will see how the Interface driver is designed
and registered to the usb-bus,
and how those usb drivers can be probed later 
when the new usb device is plugged in. 

##Registering USB interface driver

```c
/**
 * module_usb_driver() - Helper macro for registering a USB driver
 * @__usb_driver: usb_driver struct
 * 
 * Helper macro for USB drivers which do not do anything special in module
 * init/exit. This eliminates a lot of boilerplate. Each module may only
 * use this macro once, and calling it replaces module_init() and module_exit()
 */
#define module_usb_driver(__usb_driver) \
        module_driver(__usb_driver, usb_register, \
                       usb_deregister)
```
To register interface usb driver,
you can utilize the module_usb_driver macro that 
automatically implements the initialization function of the interface driver.
This initialiation function only contains the usb_register macro
that invokes usb_register_driver function.
This usb_register_driver function actually registers the interface driver.
For the detailed explanation about this function is described in previous posting. 

##How the USB sub-system matches the device to its associated driver?
Whether the device is a real usb device or its interface,
both should be registered on the usb-bus.
Therefore, when the device and interfaces are added to the usb-bus,
its probe function, usb_device_match function will be invoked 
after the device is registered.


```c
static int usb_device_match(struct device *dev, struct device_driver *drv)
{
        /* devices and interfaces are handled separately */
        if (is_usb_device(dev)) {
                struct usb_device *udev;
                struct usb_device_driver *udrv;

                /* interface drivers never match devices */
                if (!is_usb_device_driver(drv))
                        return 0;

                udev = to_usb_device(dev);
                udrv = to_usb_device_driver(drv);

                /* If the device driver under consideration does not have a
                 * id_table or a match function, then let the driver's probe
                 * function decide.
                 */
                if (!udrv->id_table && !udrv->match)
                        return 1;

                return usb_driver_applicable(udev, udrv);

        } else if (is_usb_interface(dev)) {
                struct usb_interface *intf;
                struct usb_driver *usb_drv;
                const struct usb_device_id *id;

                /* device drivers never match interfaces */
                if (is_usb_device_driver(drv))
                        return 0;

                intf = to_usb_interface(dev);
                usb_drv = to_usb_driver(drv);

                id = usb_match_id(intf, usb_drv->id_table);
                if (id)
                        return 1;

                id = usb_match_dynamic_id(intf, usb_drv);
                if (id)
                        return 1;
        }

        return 0;
}
```
The match function has different behavior depending on 
whether it is usb device or usb interface.
Note that the device object passed to the probe function
is not a usb or interface specific device structure, but
a generic device structure representing any device.


###Device type for USB system
```c
static inline int is_usb_device(const struct device *dev)
{
        return dev->type == &usb_device_type;
}

static inline int is_usb_interface(const struct device *dev)
{
        return dev->type == &usb_if_device_type;
}
```

Because the device structure is not only used for representing the USB device and its interface device,
but also for any other devices in the linux driver sub-system,
it it not a good way to add another member field for distinguishing 
USB interface and driver.
Instead of adding another field,
usb sub-system utilize the type field of the device structure. 

```c
/*
 * The type of device, "struct device" is embedded in. A class
 * or bus can contain devices of different types
 * like "partitions" and "disks", "mouse" and "event".
 * This identifies the device type and carries type-specific
 * information, equivalent to the kobj_type of a kobject.
 * If "name" is specified, the uevent will contain it in
 * the DEVTYPE variable.
 */
struct device_type {
        const char *name;
        const struct attribute_group **groups;
        int (*uevent)(struct device *dev, struct kobj_uevent_env *env);
        char *(*devnode)(struct device *dev, umode_t *mode,
                         kuid_t *uid, kgid_t *gid);
        void (*release)(struct device *dev);

        const struct dev_pm_ops *pm;
};

struct device_type usb_device_type = {
        .name =         "usb_device",
        .release =      usb_release_dev,
        .uevent =       usb_dev_uevent,
        .devnode =      usb_devnode,
#ifdef CONFIG_PM
        .pm =           &usb_device_pm_ops,
#endif  
};                  
              
struct device_type usb_if_device_type = {
        .name =         "usb_interface",
        .release =      usb_release_interface,
        .uevent =       usb_if_uevent,
}; 
```

As shown in the above code,
each USB subsystem utilize the two different types of device 
usb_device_type and usb_if_device_type.
Actually there are two more types that are not discovered in this posting,
type for USB endpoints and USB port. 
We will not cover them because they are not related to 
binding the driver to the hot-plugged USB device and its interface. 

###Driver type for USB drivers
```c
static inline int is_usb_device_driver(struct device_driver *drv)
{                       
        return container_of(drv, struct usbdrv_wrap, driver)->
                        for_devices;
}   
```
You might remember the usb_register_device_driver(&usb_generic_driver, THIS_MODULE) function invocation
in the usb_init function in the previous blog posting.
At the first glance, it is hard to understand 
how is that function is different form the 
usb_register_driver function used for registering the interface drivers.
Most of the time you will utilize the usb_register_driver
through the usb_register macro
because registering interface driver for your USB interfaces 
is your first priority job
to use your USB device on the Linux system.

When you compare the two function line by line,
you can easily find that for_devices field is only set
when the driver is registered through the 
usb_register_device_driver. 
And also you can find that different probe function is assigned 
to the driver attached to the usb-bus. 

Now the secret can be revealed.
The is_usb_device_driver checks whether the for_device has been set,
which means the current driver passed to this macro is designed for managing 
entire *USB devices* on the USB subsystem. 
From the name of the driver and its probe function
you can also infer its purpose,
usb_generic_driver and usb_generic_driver_match.

The importance of this macro is 
you can always select the device driver for the USB device 
when the USB device wants to be registered to the USB bus.
We will soon see how this macro is used 
for the USB matching function.

###USB interface device utilizes id_table
```c
        } else if (is_usb_interface(dev)) {
                struct usb_interface *intf;
                struct usb_driver *usb_drv;
                const struct usb_device_id *id;

                /* device drivers never match interfaces */
                if (is_usb_device_driver(drv))
                        return 0;

                intf = to_usb_interface(dev);
                usb_drv = to_usb_driver(drv);

                id = usb_match_id(intf, usb_drv->id_table);
                if (id)
                        return 1;

                id = usb_match_dynamic_id(intf, usb_drv);
                if (id)
                        return 1;
        }



```
Although the USB device should be matched and probed first
before the interface device can be populated,
we will take a look at how the match function works
when the interface device has been passed.
This is because USB interface always utilize the id_table mechanism for matching the 
interface to its supporting driver,
but the USB device may or may not contain a id_table and defer
the matching to the later probing.

Anyway, 
first of all, to figure out whether the current device is 
USB interface device,
it invokes is_usb_device macro.
when the device is turned out to be interface device,
then it checks current device driver passed to the match function
is an interface driver not the USB device driver 
with the help of isb_usb_device_driver macro.
When those conditionals are passed,
then the interface object can be retrieved from the device structure.
The contain_of macro can do magic here;
because the device structure is embedded in the interface object.
When the target interface is retrieved,
it invokes usb_match_id function. 

```c
/**
 * usb_match_id - find first usb_device_id matching device or interface
 * @interface: the interface of interest
 * @id: array of usb_device_id structures, terminated by zero entry
 *
 * usb_match_id searches an array of usb_device_id's and returns
 * the first one matching the device or interface, or null.
 * This is used when binding (or rebinding) a driver to an interface.
 * Most USB device drivers will use this indirectly, through the usb core,
 * but some layered driver frameworks use it directly.
const struct usb_device_id *usb_match_id(struct usb_interface *interface,
                                         const struct usb_device_id *id)
{
        /* proc_connectinfo in devio.c may call us with id == NULL. */
        if (id == NULL)
                return NULL;

        /* It is important to check that id->driver_info is nonzero,
           since an entry that is all zeroes except for a nonzero
           id->driver_info is the way to create an entry that
           indicates that the driver want to examine every
           device and interface. */
        for (; id->idVendor || id->idProduct || id->bDeviceClass ||
               id->bInterfaceClass || id->driver_info; id++) {
                if (usb_match_one_id(interface, id))
                        return id;
        }

        return NULL;
}

/* returns 0 if no match, 1 if match */
int usb_match_one_id(struct usb_interface *interface,
                     const struct usb_device_id *id)
{
        struct usb_host_interface *intf;
        struct usb_device *dev;

        /* proc_connectinfo in devio.c may call us with id == NULL. */
        if (id == NULL)
                return 0;

        intf = interface->cur_altsetting;
        dev = interface_to_usbdev(interface);

        if (!usb_match_device(dev, id))
                return 0;

        return usb_match_one_id_intf(dev, intf, id);
}

/* returns 0 if no match, 1 if match */
int usb_match_device(struct usb_device *dev, const struct usb_device_id *id)
{
        if ((id->match_flags & USB_DEVICE_ID_MATCH_VENDOR) &&
            id->idVendor != le16_to_cpu(dev->descriptor.idVendor))
                return 0;

        if ((id->match_flags & USB_DEVICE_ID_MATCH_PRODUCT) &&
            id->idProduct != le16_to_cpu(dev->descriptor.idProduct))
                return 0;

        /* No need to test id->bcdDevice_lo != 0, since 0 is never
           greater than any unsigned number. */
        if ((id->match_flags & USB_DEVICE_ID_MATCH_DEV_LO) &&
            (id->bcdDevice_lo > le16_to_cpu(dev->descriptor.bcdDevice)))
                return 0;

        if ((id->match_flags & USB_DEVICE_ID_MATCH_DEV_HI) &&
            (id->bcdDevice_hi < le16_to_cpu(dev->descriptor.bcdDevice)))
                return 0;

        if ((id->match_flags & USB_DEVICE_ID_MATCH_DEV_CLASS) &&
            (id->bDeviceClass != dev->descriptor.bDeviceClass))
                return 0;

        if ((id->match_flags & USB_DEVICE_ID_MATCH_DEV_SUBCLASS) &&
            (id->bDeviceSubClass != dev->descriptor.bDeviceSubClass))
                return 0;

        if ((id->match_flags & USB_DEVICE_ID_MATCH_DEV_PROTOCOL) &&
            (id->bDeviceProtocol != dev->descriptor.bDeviceProtocol))
                return 0;

        return 1;
}

/* returns 0 if no match, 1 if match */
int usb_match_one_id_intf(struct usb_device *dev,
                          struct usb_host_interface *intf,
                          const struct usb_device_id *id)
{
        /* The interface class, subclass, protocol and number should never be
         * checked for a match if the device class is Vendor Specific,
         * unless the match record specifies the Vendor ID. */
        if (dev->descriptor.bDeviceClass == USB_CLASS_VENDOR_SPEC &&
                        !(id->match_flags & USB_DEVICE_ID_MATCH_VENDOR) &&
                        (id->match_flags & (USB_DEVICE_ID_MATCH_INT_CLASS |
                                USB_DEVICE_ID_MATCH_INT_SUBCLASS |
                                USB_DEVICE_ID_MATCH_INT_PROTOCOL |
                                USB_DEVICE_ID_MATCH_INT_NUMBER)))
                return 0;
        
        if ((id->match_flags & USB_DEVICE_ID_MATCH_INT_CLASS) &&
            (id->bInterfaceClass != intf->desc.bInterfaceClass))
                return 0;
                
        if ((id->match_flags & USB_DEVICE_ID_MATCH_INT_SUBCLASS) &&
            (id->bInterfaceSubClass != intf->desc.bInterfaceSubClass))
                return 0;
        
        if ((id->match_flags & USB_DEVICE_ID_MATCH_INT_PROTOCOL) &&
            (id->bInterfaceProtocol != intf->desc.bInterfaceProtocol))
                return 0;

        if ((id->match_flags & USB_DEVICE_ID_MATCH_INT_NUMBER) &&
            (id->bInterfaceNumber != intf->desc.bInterfaceNumber))
                return 0;
        
        return 1;
}

```
The first for loop in the usb_match_one_id function 
invokes usb_match_one_id with every USB device & interface information
stored in the device_id table 
until the match happens.

Each entry in the id_table not only contains information of the USB device itself 
associated with current interface, but also the information of each interface.
invokes usb_match_one_id function with each interface information.

Therefore, it need to check 
whether current interface has been populated by a USB device 
supported by the matching driver. 
The usb_match_device function
check USB device information stored in the usb_device structure 
associated with current interface driver.
Because the interface driver has a reference of the USB device 
that populated current interface,
it can retrieve the reference to the parent USB device.
And because the USB device contains its USB device specific information
such as vendorID, productID,
based on the match_flags of the id,
it checks whether the match occurs.

If the matching for the device information is done, 
then it invokes usb_match_one_id_intf function to further match
the interface specific information.

When all those conditional statmenets are passed in two functions,
it means that the current USB information stored in the Nth location of the id_table,
it returns 1 to the usb_match_id function.


###USB device needs to be handled by the USB device driver
```c
        if (is_usb_device(dev)) {
                struct usb_device *udev;
                struct usb_device_driver *udrv;

                /* interface drivers never match devices */
                if (!is_usb_device_driver(drv))
                        return 0;

                udev = to_usb_device(dev);
                udrv = to_usb_device_driver(drv);

                /* If the device driver under consideration does not have a
                 * id_table or a match function, then let the driver's probe
                 * function decide.
                 */
                if (!udrv->id_table && !udrv->match)
                        return 1;

                return usb_driver_applicable(udev, udrv);

```
When the current device used for matching is USB device not an interface,
known by the is_usb_device macro,
it first checks the current driver is the USB device driver.
Because usb_init function registers only one USB device driver,
usb_generic_driver,
until that driver is found, it will keep returning 0.

When the USB device driver is found,
it first checks whether the driver has 
id_table and match callback function both
(remind that current matching function is
a callback match function of the usb_bus_type).
When both of them doesn't exist,
it just returns value 1.
And because usb_generic_driver doesn't have match function and id_table field
it will return 1 and defer all the further job to its probe function,
usb_generic_driver_probe.

##After matching, invoke probe of the matching driver
Note that based on the USB device type,
USB device or USB interface,
different probe function will be invoked. 


###USB device is handled by the USB device driver
For a USB device,
it always matches with a USB device driver, usb_generic_driver.
Therefore, 
when the probe function is invoked as a result of successful matching,
it always invokes the usb_generic_driver_probe function.

```c
int usb_generic_driver_probe(struct usb_device *udev)
{
        int err, c;

        /* Choose and set the configuration.  This registers the interfaces
         * with the driver core and lets interface drivers bind to them.
         */
        if (udev->authorized == 0)
                dev_err(&udev->dev, "Device is not authorized for usage\n");
        else {
                c = usb_choose_configuration(udev);
                if (c >= 0) {
                        err = usb_set_configuration(udev, c);
                        if (err && err != -ENODEV) {
                                dev_err(&udev->dev, "can't set config #%d, error %d\n",
                                        c, err);
                                /* This need not be fatal.  The user can try to
                                 * set other configurations. */
                        }
                }
        }
        /* USB device state == configured ... usable */
        usb_notify_add_device(udev);

        return 0;
}
```
There are two important functions inside the probe function:
usb_choose_configuration and usb_set_configuration.
The first function chooses the best suitable configuration
from the availables ones supported by the USB device.
The details will not be convered in this posting.
When the configuration is chosen, 
it returns the index of configuration.
With the index, it invokes usb_set_configuration.
Currently, we only have USB device provided configuration information
stored in the descriptor.
Therefore, we should set the selected configuration
to allow Linux USB subsystem can manage it 
for further operations. 

###usb_set_configuration, populating the interface devices
Because the usb_set_configuration is too complex to take a look at its entire operation in this posting,
we will study only fractions of it related to the interface device allocation
and binding to the driver. 

```c
int usb_set_configuration(struct usb_device *dev, int configuration)
{
        int i, ret;
        struct usb_host_config *cp = NULL;
        struct usb_interface **new_interfaces = NULL;
        struct usb_hcd *hcd = bus_to_hcd(dev->bus);
        int n, nintf;

        if (dev->authorized == 0 || configuration == -1)
                configuration = 0;
        else {  
                for (i = 0; i < dev->descriptor.bNumConfigurations; i++) {
                        if (dev->config[i].desc.bConfigurationValue ==
                                        configuration) {
                                cp = &dev->config[i];
                                break;
                        }
                }
        }
        if ((!cp && configuration != 0))
                return -EINVAL;

        /* The USB spec says configuration 0 means unconfigured.
         * But if a device includes a configuration numbered 0,
         * we will accept it as a correctly configured state.
         * Use -1 if you really want to unconfigure the device.
         */
        if (cp && configuration == 0)
                dev_warn(&dev->dev, "config 0 descriptor??\n");

        /* Allocate memory for new interfaces before doing anything else,
         * so that if we run out then nothing will have changed. */
        n = nintf = 0;
        if (cp) {
                nintf = cp->desc.bNumInterfaces;
                new_interfaces = kmalloc_array(nintf, sizeof(*new_interfaces),
                                               GFP_NOIO);
                if (!new_interfaces)
                        return -ENOMEM;
                
                for (; n < nintf; ++n) {
                        new_interfaces[n] = kzalloc(
                                        sizeof(struct usb_interface),
                                        GFP_NOIO);
                        if (!new_interfaces[n]) {
                                ret = -ENOMEM;
free_interfaces:                
                                while (--n >= 0)
                                        kfree(new_interfaces[n]);
                                kfree(new_interfaces);
                                return ret;
                        }
                }
                
                i = dev->bus_mA - usb_get_max_power(dev, cp);
                if (i < 0)
                        dev_warn(&dev->dev, "new config #%d exceeds power "
                                        "limit by %dmA\n",
                                        configuration, -i);
        }
```
Because the configuration number has been chosen by the usb_choose_configuration function,
we can understand which configuration of the USB device should be enabled.
Because usb_device can maintain all configurations 
provided by the USB device,
it first choose the selected configuration based on the configuration index parameter.
And then it allocates the interfaces 
supported by the selected configuration.
Each configuration can support different number of interfaces,
so based on the bNumInterfaces filed of the descriptor of the selected configuration,
it allocates memory for the interfaces.

After the memory space for interfaces are allocated,
it needs to be initialized.

```c
        /*
         * Initialize the new interface structures and the
         * hc/hcd/usbcore interface/endpoint state.
         */
        for (i = 0; i < nintf; ++i) {
                struct usb_interface_cache *intfc;
                struct usb_interface *intf;
                struct usb_host_interface *alt;
                u8 ifnum;

                cp->interface[i] = intf = new_interfaces[i];
                intfc = cp->intf_cache[i];
                intf->altsetting = intfc->altsetting;
                intf->num_altsetting = intfc->num_altsetting;
                intf->authorized = !!HCD_INTF_AUTHORIZED(hcd);
                kref_get(&intfc->ref);

                alt = usb_altnum_to_altsetting(intf, 0);

                /* No altsetting 0?  We'll assume the first altsetting.
                 * We could use a GetInterface call, but if a device is
                 * so non-compliant that it doesn't have altsetting 0
                 * then I wouldn't trust its reply anyway.
                 */
                if (!alt)
                        alt = &intf->altsetting[0];

                ifnum = alt->desc.bInterfaceNumber;
                intf->intf_assoc = find_iad(dev, cp, ifnum);
                intf->cur_altsetting = alt;
                usb_enable_interface(dev, intf, true);
                intf->dev.parent = &dev->dev;
                if (usb_of_has_combined_node(dev)) {
                        device_set_of_node_from_dev(&intf->dev, &dev->dev);
                } else {
                        intf->dev.of_node = usb_of_get_interface_node(dev,
                                        configuration, ifnum);
                }
                ACPI_COMPANION_SET(&intf->dev, ACPI_COMPANION(&dev->dev));
                intf->dev.driver = NULL;
                intf->dev.bus = &usb_bus_type;
                intf->dev.type = &usb_if_device_type;
                intf->dev.groups = usb_interface_groups;
                INIT_WORK(&intf->reset_ws, __usb_queue_reset_device);
                intf->minor = -1;
                device_initialize(&intf->dev);
                pm_runtime_no_callbacks(&intf->dev);
                dev_set_name(&intf->dev, "%d-%s:%d.%d", dev->bus->busnum,
                                dev->devpath, configuration, ifnum);
                usb_get_dev(dev);
        }
        kfree(new_interfaces);
```
Here, the nintf means the number of interfaces 
should be supported for the selected configuration.
Each interface is set to beattached to the usb_bus_type bus,
and has usb_if_device_type as its type
(seen in the match function before).

```c
        /* Now that all the interfaces are set up, register them
         * to trigger binding of drivers to interfaces.  probe()
         * routines may install different altsettings and may
         * claim() any interfaces not yet bound.  Many class drivers
         * need that: CDC, audio, video, etc.
         */
        for (i = 0; i < nintf; ++i) {
                struct usb_interface *intf = cp->interface[i];

                if (intf->dev.of_node &&
                    !of_device_is_available(intf->dev.of_node)) {
                        dev_info(&dev->dev, "skipping disabled interface %d\n",
                                 intf->cur_altsetting->desc.bInterfaceNumber);
                        continue;
                }

                dev_dbg(&dev->dev,
                        "adding %s (config #%d, interface %d)\n",
                        dev_name(&intf->dev), configuration,
                        intf->cur_altsetting->desc.bInterfaceNumber);
                device_enable_async_suspend(&intf->dev);
                ret = device_add(&intf->dev);
                if (ret != 0) {
                        dev_err(&dev->dev, "device_add(%s) --> %d\n",
                                dev_name(&intf->dev), ret);
                        continue;
                }
                create_intf_ep_devs(intf);
        }
```
After the interface has been initialized,
it should be registered to the usb bus to be utilized.
Note that driver field of the interface device is passed to the device_add function.
Because this device is set to be attached to the usb_bus_type bus,
the same match function we've analyzed before will be invoked once again,
usb_device_match.
This time, the device passed to the usb_device_match is the interface,
it will traverse entire registered interface drivers and 
tries to find the driver supporting current interface device.
Note that the id_table will be used for matching.
After the interface device matches with a specific interface driver,
it will end up calling the probe function of the driver.
Note that the probe function called at this time is not a
probe function of the USB device driver,
which led us to populate the interface devices.
This time the probe function registered in the matched device driver will be invoked instead!
Yeah~! now your USB device interface is bound to a driver and 
can be managed by the Linux from now on. 


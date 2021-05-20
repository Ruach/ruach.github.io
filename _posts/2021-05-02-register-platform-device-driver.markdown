---
layout: post
titile: "How to register platform driver?"
categories: linux, embedded-linux
---
We will cover how the platform device drivers 
can be registered and managed by the platform device bus subsystem.

```c
struct platform_driver {
        int (*probe)(struct platform_device *);
        int (*remove)(struct platform_device *);
        void (*shutdown)(struct platform_device *);
        int (*suspend)(struct platform_device *, pm_message_t state);
        int (*resume)(struct platform_device *);
        struct device_driver driver;
        const struct platform_device_id *id_table;
        bool prevent_deferred_probe;
}

/* module_platform_driver() - Helper macro for drivers that don't do
 * anything special in module init/exit.  This eliminates a lot of
 * boilerplate.  Each module may only use this macro once, and
 * calling it replaces module_init() and module_exit()
 */
#define module_platform_driver(__platform_driver) \
        module_driver(__platform_driver, platform_driver_register, \
                        platform_driver_unregister)
/*
 * use a macro to avoid include chaining to get THIS_MODULE
 */
#define platform_driver_register(drv) \
        __platform_driver_register(drv, THIS_MODULE)
extern int __platform_driver_register(struct platform_driver *,
                                        struct module *);
extern void platform_driver_unregister(struct platform_driver *);
```
Every device driver who want to register their driver as platform device
should utilize pre-defined macro or invoke proper platform driver registration APIs
at their driver initialization code.
%
Most kernel device driver utilizes the macro 
compared to have their own APIs to register the device driver
because they don't require any other complicated operations 
except registering the driver.
Therefore, utilizing the macro will remove boilerplate code 
required for registering your driver to platform driver
and make code looks simple.

Above macro automatically generates 
initialization and de-initialization function for
your platform device driver.
It just invokes platform_driver_register and platform_driver_unregister function 
on module init and exit respectively. 
Both macro requires a platform_driver structure object, and
populating proper platform_driver structure representing current device driver
should be done by the device driver itself.
We will take a look at platform device driver registeration process in detail.

```c
/**
 * __platform_driver_register - register a driver for platform-level devices
 * @drv: platform driver structure
 * @owner: owning module/driver
 */
int __platform_driver_register(struct platform_driver *drv,
                                struct module *owner)
{
        drv->driver.owner = owner;
        drv->driver.bus = &platform_bus_type;
 
        return driver_register(&drv->driver);
}     
```
Even though the device driver should provide the platform_driver 
and its associated call-back functions,
it is not driver's duty to allocate a driver structure 
used for actual device driver registration process.
Therefore, 
the above function and further apis for platform device
will populate the driver structure.
Also, because driver registration process utilize the common driver core apis 
that can be used for every driver registration 
regardless of the bus type,
it should set the generic driver object and pass it to the registration api.
First of all,
the bus_type object for platform device, platform_bus_type 
should be set as its bus
because this driver is supposed to support platform devices,
After the member field of the generic driver object has been filled out,
it invoked driver_register api.


```c
/**
 * driver_register - register driver with bus
 * @drv: driver to register
 *
 * We pass off most of the work to the bus_add_driver() call,
 * since most of the things we have to do deal with the bus
 * structures.
 */
int driver_register(struct device_driver *drv)
{
        int ret;
        struct device_driver *other;
 
        if (!drv->bus->p) {
                pr_err("Driver '%s' was unable to register with bus_type '%s' because the bus was not initialized.\n",
                           drv->name, drv->bus->name);
                return -EINVAL;
        }
 
        if ((drv->bus->probe && drv->probe) ||
            (drv->bus->remove && drv->remove) ||
            (drv->bus->shutdown && drv->shutdown))
                pr_warn("Driver '%s' needs updating - please use "
                        "bus_type methods\n", drv->name);
        
        other = driver_find(drv->name, drv->bus);
        if (other) {
                pr_err("Error: Driver '%s' is already registered, "
                        "aborting...\n", drv->name);
                return -EBUSY;
        }
        
        ret = bus_add_driver(drv);
        if (ret)
                return ret;
        ret = driver_add_groups(drv, drv->groups);
        if (ret) {
                bus_remove_driver(drv);
                return ret;
        }
        kobject_uevent(&drv->p->kobj, KOBJ_ADD);
        
        return ret;
}
EXPORT_SYMBOL_GPL(driver_register);
```
Note that driver_register is not bus-specific api to register the driver.
It is a generic api to register device driver structure to the bus.
This function firstly checks 
whether the bus_type has been properly initialized and registered 
to the system by checking the presence of private sub-system of the bus. 
To understand how the private subsystem has been allocated for a bus,
you might want to check previous posting. 

And then not to register same named device driver more than once,
it checks if the bus attached to the device_driver structure 
already has the same named device driver. 
If there is nothing, then it delegates
most of the driver registering process
to bus_add_driver function.

```c
struct driver_private {
        struct kobject kobj;
        struct klist klist_devices;
        struct klist_node knode_bus;
        struct module_kobject *mkobj;
        struct device_driver *driver;
};

/**
 * bus_add_driver - Add a driver to the bus.
 * @drv: driver.
 */
int bus_add_driver(struct device_driver *drv)
{
        struct bus_type *bus;
        struct driver_private *priv;
        int error = 0;

        bus = bus_get(drv->bus);
        if (!bus)
                return -EINVAL;

        pr_debug("bus: '%s': add driver %s\n", bus->name, drv->name);

        priv = kzalloc(sizeof(*priv), GFP_KERNEL);
        if (!priv) {
                error = -ENOMEM;
                goto out_put_bus;
        }
        klist_init(&priv->klist_devices, NULL, NULL);
        priv->driver = drv;
        drv->p = priv;
        priv->kobj.kset = bus->p->drivers_kset;
        error = kobject_init_and_add(&priv->kobj, &driver_ktype, NULL,
                                     "%s", drv->name);
        if (error)
                goto out_unregister;

        klist_add_tail(&priv->knode_bus, &bus->p->klist_drivers);
        if (drv->bus->p->drivers_autoprobe) {
                error = driver_attach(drv);
                if (error)
                        goto out_unregister;
        }
        module_add_driver(drv->owner, drv);

        error = driver_create_file(drv, &driver_attr_uevent);
        if (error) {
                printk(KERN_ERR "%s: uevent attr (%s) failed\n",
                        __func__, drv->name);
        }
        error = driver_add_groups(drv, bus->drv_groups);
        if (error) {
                /* How the hell do we get out of this pickle? Give up */
                printk(KERN_ERR "%s: driver_create_groups(%s) failed\n",
                        __func__, drv->name);
        }

        if (!drv->suppress_bind_attrs) {
                error = add_bind_files(drv);
                if (error) {
                        /* Ditto */
                        printk(KERN_ERR "%s: add_bind_files(%s) failed\n",
                                __func__, drv->name);
                }
        }

        return 0;

out_unregister:
        kobject_put(&priv->kobj);
        /* drv->p is freed in driver_release()  */
        drv->p = NULL;
out_put_bus:
        bus_put(bus);
        return error;
}
```
The first thing done by the bus_add_driver function is 
allocating driver's private data 
used to memorize the driver specific information

In detail,
driver_private is used to manage those private information 
related to current device driver.
For example,
it has klist_devices klist telling
which devices has been bound to current driver and 
knode_bus which is a knode object of the bus
that we are trying to register our driver to
It resets the klist_devices list first using klist_init function
because there should be no devices attached to current device
After the driver_private object has been initialized, 
it should be added to the driver.

And then we need to register our driver to the bus.
To do that klist_add_tail function will
add our driver_private's knodw to the 
klist_driver list of the subsystem of the target bus.
%
When the bus has been initialized 
if the bus has been configured to probe the device
at every driver registration (drivers_autoprobe flag)
it invokes the driver_attach function
to check if there exists device 
hat can be bound to the newly registered driver.

```c
/**
 * driver_attach - try to bind driver to devices.
 * @drv: driver.
 *
 * Walk the list of devices that the bus has on it and try to
 * match the driver with each one.  If driver_probe_device()
 * returns 0 and the @dev->driver is set, we've found a
 * compatible pair.
 */
int driver_attach(struct device_driver *drv)
{
        return bus_for_each_dev(drv->bus, NULL, drv, __driver_attach);
}
EXPORT_SYMBOL_GPL(driver_attach);

static int __driver_attach(struct device *dev, void *data)
{
        struct device_driver *drv = data;
        int ret;

        /*
         * Lock device and try to bind to it. We drop the error
         * here and always return 0, because we need to keep trying
         * to bind to devices and some drivers will return an error
         * simply if it didn't support the device.
         *
         * driver_probe_device() will spit a warning if there
         * is an error.
         */

        ret = driver_match_device(drv, dev);
        if (ret == 0) {
                /* no match */
                return 0;
        } else if (ret == -EPROBE_DEFER) {
                dev_dbg(dev, "Device match requests probe deferral\n");
                driver_deferred_probe_add(dev);
        } else if (ret < 0) {
                dev_dbg(dev, "Bus failed to match device: %d\n", ret);
                return ret;
        } /* ret > 0 means positive match */

        if (driver_allows_async_probing(drv)) {
                /*
                 * Instead of probing the device synchronously we will
                 * probe it asynchronously to allow for more parallelism.
                 *
                 * We only take the device lock here in order to guarantee
                 * that the dev->driver and async_driver fields are protected
                 */
                dev_dbg(dev, "probing driver %s asynchronously\n", drv->name);
                device_lock(dev);
                if (!dev->driver) {
                        get_device(dev);
                        dev->p->async_driver = drv;
                        async_schedule_dev(__driver_attach_async_helper, dev);
                }
                device_unlock(dev);
                return 0;
        }

        device_driver_attach(drv, dev);

        return 0;
}

```
driver_attach function invokes __driver_attach function 
against all devices registered to the bus 
our device driver attached.
The driver_match_device matches the driver with the tarversed device
(we covered the details about driver_match_device in previous posting).
If the matching device found,
it invokes device_driver_attach to manually bind device to the driver.

```c
/**
 * device_driver_attach - attach a specific driver to a specific device
 * @drv: Driver to attach
 * @dev: Device to attach it to
 *
 * Manually attach driver to a device. Will acquire both @dev lock and
 * @dev->parent lock if needed.
 */
int device_driver_attach(struct device_driver *drv, struct device *dev)
{
        int ret = 0;

        __device_driver_lock(dev, dev->parent);

        /*
         * If device has been removed or someone has already successfully
         * bound a driver before us just skip the driver probe call.
         */
        if (!dev->p->dead && !dev->driver)
                ret = driver_probe_device(drv, dev);

        __device_driver_unlock(dev, dev->parent);

        return ret;
}
```
If the device is not dead and has not been bound to any device driver,
then it invokes driver_probe_device to actually bind the device to driver.
All the details are already covered in the previous posting.
That's it! We registered our platform device driver to the platform bus






XXX:move to other posting.

```c
 399 /**
 400  * bus_for_each_drv - driver iterator
 401  * @bus: bus we're dealing with.
 402  * @start: driver to start iterating on.
 403  * @data: data to pass to the callback.
 404  * @fn: function to call for each driver.
 405  *
 406  * This is nearly identical to the device iterator above.
 407  * We iterate over each driver that belongs to @bus, and call
 408  * @fn for each. If @fn returns anything but 0, we break out
 409  * and return it. If @start is not NULL, we use it as the head
 410  * of the list.
 411  *
 412  * NOTE: we don't return the driver that returns a non-zero
 413  * value, nor do we leave the reference count incremented for that
 414  * driver. If the caller needs to know that info, it must set it
 415  * in the callback. It must also be sure to increment the refcount
 416  * so it doesn't disappear before returning to the caller.
 417  */
 418 int bus_for_each_drv(struct bus_type *bus, struct device_driver *start,
 419                      void *data, int (*fn)(struct device_driver *, void *))
 420 {
 421         struct klist_iter i;
 422         struct device_driver *drv;
 423         int error = 0;
 424 
 425         if (!bus)
 426                 return -EINVAL;
 427 
 428         klist_iter_init_node(&bus->p->klist_drivers, &i,
 429                              start ? &start->p->knode_bus : NULL);
 430         while ((drv = next_driver(&i)) && !error)
 431                 error = fn(drv, data);
 432         klist_iter_exit(&i);
 433         return error;
 434 }

 387 static struct device_driver *next_driver(struct klist_iter *i)
 388 {
 389         struct klist_node *n = klist_next(i);
 390         struct driver_private *drv_priv;
 391 
 392         if (n) {
 393                 drv_priv = container_of(n, struct driver_private, knode_bus);
 394                 return drv_priv->driver;
 395         }
 396         return NULL;
 397 }

```
For example, bus core provides api called *bus_for_each_drv*
to run a function against every device driver registered for a bus.
It internally invokes next_driver function,
and this function can retrieve the driver 
by making use of container_of macro. 

Here, klist_iter is used to traverse klist_node 
of each device driver associated with current bus.
Also note that the traversed klist is klist_drivers,
which is the member field of subsys_private structure of the bus_type structure.

Therefore, whenever klist_next function is invoked,
it returns one klist_node associated with one device driver
we've registered to the bus before.
Note that this klist_node is the memeber field of driver_private
we've set in the bus_add_driver function.

As I told before, 
when we have a reference to klist_node of the driver,
we can retrieve the driver_private structure,
and using this reference, we can return the devive driver object itself. 
Note that this device driver structure is the wrapper device driver, drvwrap
that we generated in the usb_register_driver.

When drivers_autoprobe has been set, 
it tries to bind the devices sitting on the bus 
with the new registered driver at the driver register time. 
When you go back to the bus_register function, 
you can find that the drivers_autoprobe flag has been set by default.
Therefore, 
whenever the new device driver is trying to be registered to the bus,
it will try to bind the driver to the already found devices. 
We didn't cover the detail implementation of the driver_attach function,
but it invokes binding function against the every registered devices on the bus
that are managed by the klist. 



## Printing BAR resources information 
```cpp
int pci_assign_resource(struct pci_dev *dev, int resno)
{
        struct resource *res = dev->resource + resno;
        resource_size_t align, size;
        int ret;

        if (res->flags & IORESOURCE_PCI_FIXED)
                return 0;

        res->flags |= IORESOURCE_UNSET;
        align = pci_resource_alignment(dev, res);
        if (!align) {
                pci_info(dev, "BAR %d: can't assign %pR (bogus alignment)\n",
                         resno, res);
                return -EINVAL;
        }

        size = resource_size(res);
        ret = _pci_assign_resource(dev, resno, size, align);

        /*
         * If we failed to assign anything, let's try the address
         * where firmware left it.  That at least has a chance of
         * working, which is better than just leaving it disabled.
         */
        if (ret < 0) {
                pci_info(dev, "BAR %d: no space for %pR\n", resno, res);
                ret = pci_revert_fw_address(res, dev, resno, size);

        if (ret < 0) {
                pci_info(dev, "BAR %d: failed to assign %pR\n", resno, res);
                return ret;
        }

        res->flags &= ~IORESOURCE_UNSET;
        res->flags &= ~IORESOURCE_STARTALIGN;
        pci_info(dev, "BAR %d: assigned %pR\n", resno, res);
        if (resno < PCI_BRIDGE_RESOURCES)
                pci_update_resource(dev, resno);

        return 0;
}

                                                                    

```

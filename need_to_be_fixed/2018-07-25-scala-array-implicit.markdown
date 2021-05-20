---
layout: post
title:  "Welcome to Jekyll!"
date:   2018-07-22 23:34:50 -0700
categories: scala
---

```scala
  // Not specialized anymore since 2.13 but we still need separate methods
  // to avoid https://github.com/scala/bug/issues/10746
  implicit def genericArrayOps[T](xs: Array[T]): ArrayOps[T]          = new ArrayOps(xs)
  implicit def booleanArrayOps(xs: Array[Boolean]): ArrayOps[Boolean] = new ArrayOps(xs)
  implicit def byteArrayOps(xs: Array[Byte]): ArrayOps[Byte]          = new ArrayOps(xs)
  implicit def charArrayOps(xs: Array[Char]): ArrayOps[Char]          = new ArrayOps(xs)
  implicit def doubleArrayOps(xs: Array[Double]): ArrayOps[Double]    = new ArrayOps(xs)
  implicit def floatArrayOps(xs: Array[Float]): ArrayOps[Float]       = new ArrayOps(xs)
  implicit def intArrayOps(xs: Array[Int]): ArrayOps[Int]             = new ArrayOps(xs)
  implicit def longArrayOps(xs: Array[Long]): ArrayOps[Long]          = new ArrayOps(xs)
  implicit def refArrayOps[T <: AnyRef](xs: Array[T]): ArrayOps[T]    = new ArrayOps(xs)
  implicit def shortArrayOps(xs: Array[Short]): ArrayOps[Short]       = new ArrayOps(xs)
  implicit def unitArrayOps(xs: Array[Unit]): ArrayOps[Unit]          = new ArrayOps(xs)
```

```scala
private[scala] abstract class LowPriorityImplicits extends LowPriorityImplicits2 {
...
  implicit def wrapIntArray(xs: Array[Int]): ArraySeq.ofInt = if (xs ne null) new ArraySeq.ofInt(xs) else null
  /** @group conversions-array-to-wrapped-array */
  implicit def wrapDoubleArray(xs: Array[Double]): ArraySeq.ofDouble = if (xs ne null) new ArraySeq.ofDouble(xs) else null
  /** @group conversions-array-to-wrapped-array */
  implicit def wrapLongArray(xs: Array[Long]): ArraySeq.ofLong = if (xs ne null) new ArraySeq.ofLong(xs) else null
  /** @group conversions-array-to-wrapped-array */
  implicit def wrapFloatArray(xs: Array[Float]): ArraySeq.ofFloat = if (xs ne null) new ArraySeq.ofFloat(xs) else null
  /** @group conversions-array-to-wrapped-array */
  implicit def wrapCharArray(xs: Array[Char]): ArraySeq.ofChar = if (xs ne null) new ArraySeq.ofChar(xs) else null
  /** @group conversions-array-to-wrapped-array */
  implicit def wrapByteArray(xs: Array[Byte]): ArraySeq.ofByte = if (xs ne null) new ArraySeq.ofByte(xs) else null
  /** @group conversions-array-to-wrapped-array */
  implicit def wrapShortArray(xs: Array[Short]): ArraySeq.ofShort = if (xs ne null) new ArraySeq.ofShort(xs) else null
  /** @group conversions-array-to-wrapped-array */
  implicit def wrapBooleanArray(xs: Array[Boolean]): ArraySeq.ofBoolean = if (xs ne null) new ArraySeq.ofBoolean(xs) else null
  /** @group conversions-array-to-wrapped-array */
  implicit def wrapUnitArray(xs: Array[Unit]): ArraySeq.ofUnit = if (xs ne null) new ArraySeq.ofUnit(xs) else null
...
}
```

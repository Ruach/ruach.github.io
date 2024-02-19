---
icon: fas fa-id-card
order: 4
---

<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Responsive PDF Embed</title>
<style>
    .pdf-container {
        position: relative;
        width: 100%;
        height: 0;
        padding-bottom: 100%; /* Aspect ratio 1:1 */
    }
    .pdf-container iframe {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
    }
</style>
</head>
<body>

<div class="pdf-container">
    <iframe src="/assets/files/JAEHYUK_CV.pdf" frameborder="0"></iframe>
</div>

</body>
</html>

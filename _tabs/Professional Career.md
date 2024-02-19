---
icon: fas fa-id-card
order: 4
title: Professional Career
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
            overflow: hidden;
            padding-bottom: 100%; /* Aspect ratio 1:1 */
        }

        .pdf-container iframe {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
        }

        /* Responsive styling */
        @media only screen and (max-width: 768px) {
            /* Adjust padding-bottom for smaller screens */
            .pdf-container {
                padding-bottom: 150%; /* Adjust as needed */
            }
        }

        @media only screen and (max-width: 480px) {
            /* Further adjustments for smaller screens */
            .pdf-container {
                padding-bottom: 200%; /* Adjust as needed */
            }
        }
    </style>
</head>
<body>

<main>
    <div class="pdf-container">
        <iframe src="/assets/files/JAEHYUK_CV.pdf" frameborder="0" title="Embedded PDF"></iframe>
    </div>
    <noscript>
        <p>It seems your browser does not support JavaScript, please <a href="/assets/files/JAEHYUK_CV.pdf">download the PDF</a> instead.</p>
    </noscript>
</main>

</body>
</html>

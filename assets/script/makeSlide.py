import sys
import os



    


class slideGenerator: 
    html_str ='''
<link rel="stylesheet" href="/assets/css/slides.css">  

<div class="slideshow-container center-container">

{slide-items}

</div>
<br>

<div style="text-align:center">
{button-items}
</div>

<script defer src="/assets/js/img/slides.js"></script>
    '''
    def __init__(self, directory):
        self.directory = directory
        self.files = self.list_files()
        self.num_of_files = self.files.len();
        self.slide_items = '';
        self.button_items = '';

    def genButtonItem(file, index):
    #<span class="dot" onclick="currentSlide(1)"></span>
    
    def list_files(dir):
        try:
            files = [f for f in os.listdir(dir) if os.path.isfile(os.path.join(dir,f))]
            return files
        except Exception as e:
            print(f"An error occurred: {e}")
            return []
    
    def genItem():
        index = 0;
        for f in files_list:
            index++
            slide_items += genSlideItem(f, index)
            button_items += genButtonItem(f, index)
    def genSlideItem(file, index):
        slideTemplate = '''
<div class="mySlides fade"> 
  <div class="numbertext">1 / 3</div>
  <img src="/assets/img/jaehyuk.png" style="width:100%">
</div>
    '''
    


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script_name.py /path/to/your/image/directory")
        sys.exit(1)

    directory_path = sys.argv[1]

    slideGen = slideGenerator(directory_path)


    print(slide_items)
    #subst_dict = {"slide-items": "SLIDE-ITEMS", "button-items": "BUTTON-ITEMS"}
    #print(html_str.format(**subst_dict))

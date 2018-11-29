# BTAP eQuest to OpenStudio Geometry converter. 

This measure is a stand-alone implementation using BTAP's equest module. Until BTAP is gemified, this is to be conisdered a hard fork of that work. 

This may or may not work as this is dependant on the complexity of your model. This was created using eQuest 3.62 as the basis. So future versions may not work with this script. YMMV greatly. 

Also it has been noted that if your model has non-english charecters in any naming,  the conversion will fail. 

## Steps to convert using OS model editor. (windows)

1. Place your eQuest inp file into a folder close to the top of your drive. Ensure your file and folder name have no spaces or special charecters in it. For example a folder like
 ```
 c:\convert_file\my_equest_file.inp  
```
2. Copy this measure folder (the entire btap_equest_converter) to your measures folder. If you do not know where your measures folder is, open OpenStudio App and go to preference -> change my measures folder and it should show where it is currently.  
3. Click 'Components and Measures' -> 'Apply Measure now'
4. Search Under "Envelope" -> "Form" and you will find the "btap equest converter" to select.
5. Select it.
6. Enter the filepath of the file you want to convert. for the example above it would be like the path below. Please note that you **must** use only forward slashes, and not the traditional windows backward slashes.  
```
 c:/convert_file/my_equest_file.inp  
```
7. Hit Apply and wait. Large files may take some time. 
8. When completed is will show a report if it was sucessful. You may now save the osm file anywhere you wish and start tweaking the model as you see fit.

## FAQ
**Q**: Does this convert HVAC, schedules, spacetypes etc as well?

**A**: No it only converts the following if you are lucky.
* surfaces
* sub surfaces
* spaces
* thermal zones

**Q** How to I convert many buildings at once

**A**: You will need to understand ruby and bundler and be comfortable running scripts on the command line. But if you do..you can write a wrapper that iterates through a list of files. [Here](https://github.com/canmet-energy/btap/blob/master/measures_development/btap_equest_converter/batch_run.rb) is an example that would work on Linux systems. You would have to modify this to work with windows. 



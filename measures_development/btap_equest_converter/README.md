This measure is a stand-alone implementation using BTAP's equest module. Until BTAP is gemified, this is to be conisdered a hard fork of that work. 

This may or may not work as this is dependant on the complexity of your model. Also it has been noted that if your model has non-english charecters in any naming,  the conversion will fail. 

Step to convert using OS model editor. (windows)
0. Place your eQuest inp file into a folder close to the top of your drive. Ensure your file and folder name have no spaces or special charecters in it. For example a folder like
 ```
 c:\convert_file\my_equest_file.inp  
```
1. Copy this measure folder (the entire btap_equest_converter) to your measures folder. If you do not know where your measures folder is, open OpenStudio App and go to preference -> change my measures folder and it should show where it is currently.  
2. Click 'Components and Measures' -> 'Apply Measure now'
3. Search Under "Envelope" -> "Form" and you will find the "btap equest converter" to select.
4. Select it.
5. Enter the filepath of the file you want to convert. for the example above it would be like the path below. Please note that you **must** use only forward slashes, and not the traditional windows backward slashes.  
```
 c:/convert_file/my_equest_file.inp  
```
6. Hit Apply and wait. Large files may take some time. 
7. When completed is will show a report if it was sucessful. You may now save the osm file anywhere you wish and start tweaking the model as you see fit.
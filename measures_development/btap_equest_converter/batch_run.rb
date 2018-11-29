require "singleton"
require 'fileutils'
require 'csv'
require 'fileutils'
require "date"
require_relative "resources/btap.rb"

#List of files you want to convert...slashes are the right way.
[
    './test/4StoreyBuilding.inp',
    './test/5ZoneFloorRotationTest.inp'

].each do |inp_file|


  #Create an instances of a DOE model
  doe_model = BTAP::EQuest::DOEBuilding.new()

  #Load the inp data into the DOE model.
  doe_model.load_inp(inp_file,nil)

  #Convert the model to a OSM format.
  osm_model = doe_model.create_openstudio_model_new()

  #will save osm file to the same folder but with an osm extention.
  BTAP::FileIO::save_osm( osm_model, inp_file + ".osm" )
end

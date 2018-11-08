class BTAPCosting
  def ahu_costing(model, prototype_creator)
    air_loops = model.getAirLoopHVACs

    model.getAirLoopHVACs.each do |airloop|
      airloop.thermalZones.each do |tz|
        tz_name = tz.nameString
        tz.spaces.each do |space|
          puts "hello"
        end
      end
    end
    puts "hello"
  end
end
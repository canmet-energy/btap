#start the measure
class ServerDirectoryCleanup < OpenStudio::Ruleset::ReportingUserScript

  #define the name that a user will see, this method may be deprecated as
  #the display name in PAT comes from the name field in measure.xml
  def name
    "Server Directory Cleanup"
  end

  #define the arguments that the user will input
  def arguments()
    args = OpenStudio::Ruleset::OSArgumentVector.new
  end #end the arguments method

  #define what happens when the measure is run
  def run(runner, user_arguments)
    super(runner, user_arguments)

    #use the built-in error checking
    unless runner.validateUserArguments(arguments, user_arguments)
      false
    end

    initial_string = "The following files were in the local run directory prior to the execution of this measure: "
    Dir.entries("./../").each do |f|
      initial_string << "#{f}, "
    end
    initial_string = initial_string[0..(initial_string.length-3)]+"."
    runner.registerInitialCondition(initial_string)

    Dir.glob("./../*.sql").each do |f|
      File.delete(f)
      runner.registerInfo("Deleted #{f} from the run directory.") if !File.exist?(f)
    end
    Dir.glob("./../*.audit").each do |f|
      File.delete(f)
      runner.registerInfo("Deleted #{f} from the run directory.") if !File.exist?(f)
   end
    Dir.glob("./../in.osm").each do |f|
      File.delete(f)
      runner.registerInfo("Deleted #{f} from the run directory.") if !File.exist?(f)
    end
    Dir.glob("./../*.bnd").each do |f|
      File.delete(f)
      runner.registerInfo("Deleted #{f} from the run directory.") if !File.exist?(f)
    end
    Dir.glob("./../*.eio").each do |f|
      File.delete(f)
      runner.registerInfo("Deleted #{f} from the run directory.") if !File.exist?(f)
    end
    Dir.glob("./../*.shd").each do |f|
      File.delete(f)
      runner.registerInfo("Deleted #{f} from the run directory.") if !File.exist?(f)
    end
    Dir.glob("./../*.mdd").each do |f|
      File.delete(f)
      runner.registerInfo("Deleted #{f} from the run directory.") if !File.exist?(f)
    end
    Dir.glob("./../*.csv").each do |f|
      File.delete(f)
      runner.registerInfo("Deleted #{f} from the run directory.") if !File.exist?(f)
    end
    Dir.glob("./../*.eso").each do |f|
      File.delete(f)
      runner.registerInfo("Deleted #{f} from the run directory.") if !File.exist?(f)
    end

    final_string = "The following files were in the local run directory following to the execution of this measure: "
    Dir.entries("./..").each do |f|
      final_string << "#{f}, "
    end
    final_string = final_string[0..(final_string.length-3)]+"."
    runner.registerFinalCondition(final_string)

    true

  end #end the run method

end #end the measure

#this allows the measure to be use by the application
ServerDirectoryCleanup.new.registerWithApplication
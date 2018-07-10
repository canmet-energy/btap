require_relative '../measures_development/BTAPCostingMeasure/resources/btap_costing'
data = BTAPCosting.new()
data.create_database()
data.create_dummy_database()

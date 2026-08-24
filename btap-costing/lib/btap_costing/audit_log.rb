# The AuditLog lives in btap-audit — one implementation for the whole family.
begin
  require 'btap_audit'
rescue LoadError
  require File.expand_path('../../../btap-audit/lib/btap_audit', __dir__)
end

module BtapCosting
  AuditLog = BtapAudit::AuditLog
end

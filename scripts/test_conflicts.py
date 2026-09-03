import sys
sys.path.insert(0, r'E:\Faculty profile portal\backend')
import asyncio
from app.services.conflict_resolution import detect_conflicts

async def test():
    # Test C1: Duplicate upload
    ip_record = {'id': 'record-001', 'ip_type': 'PATENT', 'institution': 'IIT Delhi'}
    extracted = {'institution': 'IIT Delhi', 'contributor_name': 'Dr. John Smith', 'inventors': ['John Smith', 'Jane Doe']}
    
    # C1: Duplicate upload
    candidates = [{'record_id': 'existing-001', 'identifier': 'US10123456', 'confidence': 0.95}]
    conflicts = await detect_conflicts(
        ip_record, 
        extracted, 
        duplicate_candidates=candidates
    )
    print('C1 Conflicts:', len(conflicts))
    for c in conflicts:
        print('  ' + str(c['conflict_type']) + ': ' + str(c['priority']) + ' - ' + c['description'][:60] + '...')
    
    # C2: Same-name faculty
    matches = [
        {'name': 'Dr. John Smith', 'faculty_id': 'fac-001', 'confidence': 0.8},
        {'name': 'Dr. John Smith', 'faculty_id': 'fac-004', 'confidence': 0.75},
    ]
    conflicts = await detect_conflicts(
        ip_record,
        extracted,
        identity_matches=matches
    )
    print('C2 Conflicts:', len(conflicts))
    for c in conflicts:
        print('  ' + str(c['conflict_type']) + ': ' + str(c['priority']))
    
    # C3: Institution mismatch
    extracted_mismatch = {'institution': 'IIT Bombay', 'contributor_name': 'Dr. John Smith'}
    conflicts = await detect_conflicts(
        ip_record,
        extracted_mismatch
    )
    print('C3 Conflicts:', len(conflicts))
    for c in conflicts:
        print('  ' + str(c['conflict_type']) + ': ' + c['description'][:60] + '...')
    
    # C4: Missing faculty name
    extracted_no_name = {'institution': 'IIT Delhi'}
    conflicts = await detect_conflicts(ip_record, extracted_no_name)
    print('C4 Conflicts:', len(conflicts))
    for c in conflicts:
        print('  ' + str(c['conflict_type']) + ': ' + c['description'][:60] + '...')
    
    # C5: Verification mismatch
    verification = {'status': 'MISMATCH', 'details': 'Patent number not found in USPTO'}
    conflicts = await detect_conflicts(ip_record, extracted, verification_result=verification)
    print('C5 Conflicts:', len(conflicts))
    for c in conflicts:
        print('  ' + str(c['conflict_type']))
    
    # C6: AI uncertainty
    classification = {'ip_type': 'PATENT', 'confidence': 0.5}
    conflicts = await detect_conflicts(ip_record, extracted, classification_result=classification)
    print('C6 Conflicts:', len(conflicts))
    for c in conflicts:
        print('  ' + str(c['conflict_type']))
    
    # C7: Contributor order ambiguity
    inventors = ['John Smith', 'Jane Doe', 'Bob Johnson']
    conflicts = await detect_conflicts(ip_record, {'inventors': inventors})
    print('C7 Conflicts:', len(conflicts))
    for c in conflicts:
        print('  ' + str(c['conflict_type']))
    
    # C8: Patent vs Design misclassification
    classification = {'ip_type': 'DESIGN_REGISTRATION', 'confidence': 0.8}
    conflicts = await detect_conflicts(
        {'id': 'record-002', 'ip_type': 'PATENT', 'institution': 'IIT Delhi'},
        extracted,
        classification_result=classification
    )
    print('C8 Conflicts:', len(conflicts))
    for c in conflicts:
        print('  ' + str(c['conflict_type']))

asyncio.run(test())
"""Classification accuracy evaluation — Phase 7. Measurement only."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.services.ocr_pipeline import classify_document

tests = [
    ('PATENT NUMBER: IN202017004567\nTitle of Invention: A System for Cloud Computing\nDate of Grant: 15/03/2024\nApplicant: Tata Consultancy\nInventor: Dr. Ramesh Kumar\nClaims: What is claimed is a system comprising a processor...', 'PATENT', 'Indian patent with patent number+grant date+claims'),
    ('APPLICATION NUMBER: IN/PCT/2019/12345\nPATENT NO: 456789\nTitle: Wireless Device\nPatentee: Samsung\nSpecification: The present invention relates to...', 'PATENT', 'Patent with application+patent number'),
    ('PATENT\nUnited States Patent No. 11,234,567\nInventor: John Smith\nClaims\n1. A method for processing data...', 'PATENT', 'US patent with claims'),
    ('PATENT CERTIFICATE\nPatent Number: CN202010123456.7\nTitle: Energy Storage\nInventor: Zhang Wei\nGrant Date: 2023-08-15\nThe specification discloses...', 'PATENT', 'Chinese patent'),
    ('INVENTION PATENT\nPatent No.: ZL2021 1 0456789.3\nPatentee: Huawei\nDate of Grant: January 10, 2024\nClaims: 1. A method for manufacturing...', 'PATENT', 'Chinese invention patent with claims'),
    ('INDIAN PATENT GAZETTE\nPatent Application No.: 201817012345\nTitle: Solar Panel System\nApplicant: IIT Delhi\nAbstract: The present invention provides...', 'PATENT', 'Patent application publication'),
    ('PATENT DOCUMENT\nApplication No: PCT/IB2020/050001\nTitle: Autonomous Vehicle Navigation\nInventor: Dr. Priya Sharma\nPatentee: Tata Motors\nSpecification: The invention relates to...\nClaims: 1. An autonomous navigation system...', 'PATENT', 'PCT patent with specification+claims'),
    ('GRANTED PATENT\nPatent Number: JP2023-012345\nTitle: Robot Control Method\nDate of Grant: March 2023\nInventor: Tanaka\nPatentee: Toyota', 'PATENT', 'Japanese patent with grant date'),
    ('PATENT\nNo.: EP3456789B1\nTitle: Secure Data Transmission\nPatentee: Telefonica\nGrant date: 03 Jan 2024\nClaims: 1. A method for secure data...', 'PATENT', 'European patent with grant date+claims'),
    ('INDIAN PATENT\nPatent No.: 398765\nTitle: Agricultural Irrigation\nApplicant: Mahindra\nInventor: Rajesh Patel\nDate of Grant: 22/11/2023', 'PATENT', 'Simple Indian patent'),
    ('PATENT APPLICATION\nApplication Number: 202041006789\nTitle: Machine Learning Fraud Detection\nApplicant: Infosys\nGrant Date: 12/06/2024', 'PATENT', 'Patent application granted'),
    ('PATENT\nPatent Number: KR10-2023-0012345\nTitle: Display Device\nPatentee: Samsung Display\nClaims: 1. A display device comprising...', 'PATENT', 'Korean patent with claims'),
    ('DESIGN REGISTRATION CERTIFICATE\nDesign Number: 3045678\nTitle: Ornamental Design for a Chair\nRegistered Owner: IKEA\nDate of Registration: 15/01/2024\nClass: 06-01 Furniture', 'DESIGN_REGISTRATION', 'Standard design certificate'),
    ('REGISTERED DESIGN\nDesign No.: D/12345/67\nTitle: Mobile Phone Case\nProprietor: Apple Inc.\nLocarno Class: 14-04', 'DESIGN_REGISTRATION', 'Design with Locarno'),
    ('DESIGN\nDesign Registration Number: IND/345678/001\nTitle: Bottle Design\nApplicant: Coca-Cola\nRegistration Date: March 2024\nDesign Act, 2000', 'DESIGN_REGISTRATION', 'Indian design under Design Act'),
    ('CERTIFICATE OF REGISTRATION OF DESIGN\nDesign No: 2987654\nTitle: Automotive Wheel Rim\nProprietor: Tata Motors\nClass: 12-11 Means of Transport', 'DESIGN_REGISTRATION', 'Design certificate with class'),
    ('INDUSTRIAL DESIGN REGISTRATION\nRegistration No.: ID/2024/00456\nTitle: Electric Kettle\nOwner: Philips\nLocarno Classification: 15-04\nOrnamental appearance of the product', 'DESIGN_REGISTRATION', 'Industrial design with ornamental'),
    ('DESIGN APPLICATION\nApplication No.: 3056789\nTitle: Textile Pattern\nApplicant: Fabindia Ltd\nDesign of the ornamental features for a fabric', 'DESIGN_REGISTRATION', 'Design application with ornamental'),
    ('REGISTRATION OF DESIGN\nDesign Number: 2876543\nTitle: Speaker Grille Design\nRegistered to: Bose Corporation\nDate: 2023-11-15\nLocarno: 14-01', 'DESIGN_REGISTRATION', 'Design with registered design'),
    ('DESIGN\nDesign No: D-2024-001234\nTitle: Smartwatch Face\nApplicant: Xiaomi\nOrnamental design for an electronic device', 'DESIGN_REGISTRATION', 'Design with ornamental for device'),
    ('REGISTERED DESIGN\nDesign Registration No: 3123456\nTitle: Furniture Handle\nProprietor: Godrej\nDesign Act, 2000\nClass 06-02', 'DESIGN_REGISTRATION', 'Furniture handle design'),
    ('DESIGN CERTIFICATE\nDesign No: 2765432\nTitle: Keyboard Layout\nOwner: Microsoft\nRegistration Date: 08/02/2024\nLocarno Class: 14-01', 'DESIGN_REGISTRATION', 'Keyboard design certificate'),
    ('CERTIFICATE\nThis is to certify that the product has been tested and meets quality standards.\nCertification No: ISO-9001-2015\nIssued: January 2024', 'UNKNOWN_OTHER', 'ISO certificate - not IP'),
    ('TRADEMARK REGISTRATION\nApplication No: TM/2024/00123\nWord Mark: INNOVATECH\nClass: 09\nApplicant: TechStart Inc.', 'UNKNOWN_OTHER', 'Trademark - not patent or design'),
    ('COPYRIGHT REGISTRATION\nRegistration No: TXu-2-345-678\nTitle: Software Application v3.0\nAuthor: Dr. Suresh Kumar\nDate: 2024-01-15', 'UNKNOWN_OTHER', 'Copyright - not patent or design'),
    ('', 'UNKNOWN_OTHER', 'Empty text'),
    ('This document contains information about academic research publications and journal articles.', 'UNKNOWN_OTHER', 'Academic publication text'),
    ('MEMORANDUM OF UNDERSTANDING\nBetween Institution A and Institution B\nFor collaborative research in artificial intelligence', 'UNKNOWN_OTHER', 'MoU document'),
    ('Title: Novel Drug Delivery System\nApplicant: Cipla Ltd\nInventor: Dr. Sharma\nAbstract: The invention relates to pharmaceutical formulations...', 'PATENT', 'Patent-like without explicit number'),
    ('The present invention provides a system and method for real-time language translation. The system comprises a neural network processor trained on multilingual corpora.', 'PATENT', 'Invention abstract only'),
    ('Patent Pending\nA revolutionary approach to water purification using nanotechnology.\nApplicant: IIT Bombay', 'PATENT', 'Patent pending claim'),
    ('Design Patent Application\nTitle: Ornamental Design for Smartphone Holder\nApplicant: Belkin International', 'DESIGN_REGISTRATION', 'US Design Patent - tricky'),
    ('Research Paper: Novel Approach to Machine Learning\nAuthors: Kumar et al.\nPublished in: IEEE Transactions 2024', 'UNKNOWN_OTHER', 'Research paper - not IP'),
]

correct = 0
total = len(tests)
details = []
confusion = {'PATENT': {'PATENT': 0, 'DESIGN_REGISTRATION': 0, 'UNKNOWN_OTHER': 0},
             'DESIGN_REGISTRATION': {'PATENT': 0, 'DESIGN_REGISTRATION': 0, 'UNKNOWN_OTHER': 0},
             'UNKNOWN_OTHER': {'PATENT': 0, 'DESIGN_REGISTRATION': 0, 'UNKNOWN_OTHER': 0}}

for text, expected, desc in tests:
    result = classify_document(text, 'test.pdf')
    got = result['ip_type']
    conf = result['confidence']
    is_correct = got == expected
    if is_correct:
        correct += 1
    confusion[expected][got] += 1
    details.append((desc, expected, got, conf, 'OK' if is_correct else 'FAIL'))

print('=' * 80)
print('CLASSIFICATION ACCURACY EVALUATION')
print('=' * 80)
print('Total test documents: %d' % total)
print('Correct: %d' % correct)
print('Accuracy: %.1f%%' % (correct / total * 100))
print()
print('CONFUSION MATRIX:')
header = '%20s %12s %12s %12s' % ('', 'Pred PATENT', 'Pred DESIGN', 'Pred UNKNOWN')
print(header)
for actual in ['PATENT', 'DESIGN_REGISTRATION', 'UNKNOWN_OTHER']:
    print('Actual %12s: %12d %12d %12d' % (actual, confusion[actual]['PATENT'], confusion[actual]['DESIGN_REGISTRATION'], confusion[actual]['UNKNOWN_OTHER']))
print()

for cls in ['PATENT', 'DESIGN_REGISTRATION', 'UNKNOWN_OTHER']:
    tp = confusion[cls][cls]
    fp = sum(confusion[other][cls] for other in confusion if other != cls)
    fn = sum(confusion[cls][other] for other in confusion[cls] if other != cls)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    print('%s: precision=%.2f recall=%.2f f1=%.2f (tp=%d fp=%d fn=%d)' % (cls, precision, recall, f1, tp, fp, fn))

print()
print('DETAILS:')
for desc, expected, got, conf, status in details:
    marker = 'PASS' if status == 'OK' else 'FAIL'
    print('  [%s] %s: expected=%s got=%s conf=%.2f' % (marker, desc, expected, got, conf))

print()
print('CRITICAL CHECKS:')
design_as_patent = confusion['DESIGN_REGISTRATION']['PATENT']
patent_as_design = confusion['PATENT']['DESIGN_REGISTRATION']
print('  Design->Patent errors: %d' % design_as_patent)
print('  Patent->Design errors: %d' % patent_as_design)
if design_as_patent == 0 and patent_as_design == 0:
    print('  CRITICAL CHECK: PASSED')
else:
    print('  CRITICAL CHECK: FAILED')

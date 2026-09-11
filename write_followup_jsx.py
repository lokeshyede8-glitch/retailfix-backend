import os
out = r'e:\\Quotation\\frontend\\src\\views\\FollowupManagement.jsx'
# Read the template from a data file
data = open(r'e:\\Quotation\\backend\\followup_jsx_data.txt', encoding='utf-8').read()
open(out, 'w', encoding='utf-8').write(data)
print('Written', len(data), 'bytes')
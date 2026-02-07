# simless/test_xp_binding.py

import XPPython3
from simless.libs.fake_xp import FakeXP

# 1. Construct FakeXP
xp_instance = FakeXP(debug=True)

# 2. Bind FakeXP into XPPython3.xp
XPPython3.xp = xp_instance

# 3. Import xp AFTER binding
from XPPython3 import xp

# 4. Prove widget constants exist
print("WidgetClass_Button =", xp.WidgetClass_Button)
print("WidgetClass_MainWindow =", xp.WidgetClass_MainWindow)

# 5. Prove widget API functions exist
print("createWidget =", xp.createWidget)
print("setWidgetProperty =", xp.setWidgetProperty)

# 6. Prove graphics API exists
print("drawString =", xp.drawString)

# 7. Prove dataref API exists
print("getDataf =", xp.getDataf)

# 8. Prove flightloop API exists
print("createFlightLoop =", xp.createFlightLoop)

print("\nSUCCESS: FakeXP xp.* binding works.")

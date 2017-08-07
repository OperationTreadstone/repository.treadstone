import os, xbmc, xbmcaddon
import base64

#########################################################
### User Edit Variables #################################
#########################################################
ADDON_ID       = xbmcaddon.Addon().getAddonInfo('id')
ADDONTITLE     = 'Treadstone Installer'
EXCLUDES       = [ADDON_ID, 'repository.treadstone']
# Text File with build info in it.
BUILDFILE      = base64.b64decode('aHR0cHM6Ly9vcGVyYXRpb24udHIzYWRzdC5vbmUvYXV0b2J1aWxkcy54bWw=')
# How often you would list it to check for build updates in days
# 0 being every startup of kodi
UPDATECHECK    = 0
# Text File with apk info in it.
APKFILE        = base64.b64decode('aHR0cHM6Ly9vcGVyYXRpb24udHIzYWRzdC5vbmUvYXBrLnhtbA==')
# Text File with Youtube Videos urls.  Leave as 'http://' to ignore
YOUTUBETITLE   = 'Tricks & Tutorials'
YOUTUBEFILE    = base64.b64decode('aHR0cHM6Ly9vcGVyYXRpb24udHIzYWRzdC5vbmUveW91dHViZS54bWw=')
# Text File for addon installer.  Leave as 'http://' to ignore
ADDONFILE      = base64.b64decode('aHR0cHM6Ly9vcGVyYXRpb24udHIzYWRzdC5vbmUvYWRkb24ueG1s')
# Text File for advanced settings.  Leave as 'http://' to ignore
ADVANCEDFILE   = base64.b64decode('aHR0cHM6Ly9vcGVyYXRpb24udHIzYWRzdC5vbmUvYWR2YW5jZWQueG1s')

# Dont need to edit just here for icons stored locally
PATH           = xbmcaddon.Addon().getAddonInfo('path')
ART            = os.path.join(PATH, 'resources', 'art')

#########################################################
### THEMING MENU ITEMS ##################################
#########################################################
# If you want to use locally stored icons the place them in the Resources/Art/
# folder of the wizard then use os.path.join(ART, 'imagename.png')
# do not place quotes around os.path.join
# Example:  ICONMAINT     = os.path.join(ART, 'mainticon.png')
#           ICONSETTINGS  = 'http://aftermathwizard.net/repo/wizard/settings.png'
# Leave as http:// for default icon
ICONBUILDS     = 'http://'
ICONMAINT      = 'http://'
ICONAPK        = 'http://'
ICONADDONS     = 'http://'
ICONYOUTUBE    = 'http://'
ICONSAVE       = 'http://'
ICONTRAKT      = 'http://'
ICONREAL       = 'http://'
ICONLOGIN      = 'http://'
ICONCONTACT    = 'http://'
ICONSETTINGS   = 'http://'
# Hide the ====== seperators 'Yes' or 'No'
HIDESPACERS    = 'Yes'
# Character used in seperator
SPACER         = ''

# You can edit these however you want, just make sure that you have a %s in each of the
# THEME's so it grabs the text from the menu item
COLOR1         = 'ghostwhite'
COLOR2         = 'darkgrey'
# Primary menu items   / %s is the menu item and is required
THEME1         = '[COLOR '+COLOR1+'][B]  TREADSTONE [/COLOR][/B] [I][COLOR '+COLOR2+']%s[/COLOR][/I] '
# Build Names          / %s is the menu item and is required
THEME2         = '[COLOR '+COLOR2+']%s[/COLOR]'
# Alternate items      / %s is the menu item and is required
THEME3         = '[COLOR '+COLOR1+']%s[/COLOR]'
# Current Build Header / %s is the menu item and is required
THEME4         = '[COLOR '+COLOR1+'][B]DECLASSIFIED BUILD[/B][/COLOR] [I][COLOR '+COLOR2+']%s[/COLOR][/I]'
# Current Theme Header / %s is the menu item and is required
THEME5         = '[COLOR '+COLOR1+'][B]DECLASSIFIED THEME[/B][/COLOR] [I][COLOR '+COLOR2+']%s[/COLOR][/I]'

# Message for Contact Page
# Enable 'Contact' menu item 'Yes' hide or 'No' dont hide
HIDECONTACT    = 'No'
# You can add \n to do line breaks
CONTACT        = '[B][COLOR ghostwhite]Thanks for your trust,\r\n\r\nOperation Treadstone is now Bourne\r\n\r\nContact us: https://www.facebook.com/groups/TR3ADSTONE[/COLOR][/B]'
#Images used for the contact window.  http:// for default icon and fanart
CONTACTICON    = 'http://'
CONTACTFANART  = 'http://'
#########################################################

#########################################################
### AUTO UPDATE #########################################
########## FOR THOSE WITH NO REPO #######################
# Enable Auto Update 'Yes' or 'No'
AUTOUPDATE     = 'Yes'
# Url to wizard version
WIZARDFILE     = base64.b64decode('aHR0cHM6Ly9vcGVyYXRpb24udHIzYWRzdC5vbmUvYXV0b2J1aWxkcy54bWw=')
#########################################################

#########################################################
### AUTO INSTALL ########################################
########## REPO IF NOT INSTALLED ########################
# Enable Auto Install 'Yes' or 'No'
AUTOINSTALL    = 'Yes'
# Addon ID for the repository
REPOID         = 'repository.treadstone'
# Url to Addons.xml file in your repo folder(this is so we can get the latest version)
REPOADDONXML   = base64.b64decode('aHR0cHM6Ly9yYXcuZ2l0aHVidXNlcmNvbnRlbnQuY29tL1RSM0FEU1RPTkUvcmVwb3NpdG9yeS50cmVhZHN0b25lL21hc3Rlci9yZXBvc2l0b3J5LnRyZWFkc3RvbmUvYWRkb24ueG1s')
# Url to folder zip is located in
REPOZIPURL     = base64.b64decode('aHR0cHM6Ly9naXRodWIuY29tL1RSM0FEU1RPTkUvcmVwb3NpdG9yeS50cmVhZHN0b25lL3RyZWUvbWFzdGVyL3JlcG9zaXRvcnkudHJlYWRzdG9uZS8=')
#########################################################

#########################################################
### NOTIFICATION WINDOW##################################
#########################################################
# Enable Notification screen Yes or No
ENABLE         = 'Yes'
# Url to notification file
NOTIFICATION   = base64.b64decode('aHR0cHM6Ly9vcGVyYXRpb24udHIzYWRzdC5vbmUvbm90Zml5LnhtbA==')
# Use either 'Text' or 'Image'
HEADERTYPE     = 'Text'
HEADERMESSAGE  = ''
# url to image if using Image 424x180
HEADERIMAGE    = base64.b64decode('aHR0cHM6Ly9vcGVyYXRpb24udHIzYWRzdC5vbmUvaGVhZGVyLmpwZw==')
# Background for Notification Window
BACKGROUND     = base64.b64decode('aHR0cHM6Ly9vcGVyYXRpb24udHIzYWRzdC5vbmUvYmFja2dyb3VuZC5qcGc=')
#########################################################
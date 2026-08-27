PDFs of manuals and other useful documents to the project:

Dongle DLL manual: https://www.i2ctools.com/Downloads/USBtoI2Cpro/V6/USB-to-I2C_Professional_DLL_Users_Manual.pdf

Dongle GUI software manual: https://www.i2ctools.com/Downloads/USBtoI2Cpro/USB-to-SPI_Software_Users_Manual.pdf?_ga=2.58411946.1623653603.1787838511-886811140.1786995748

Clock software manual: https://tools.skyworksinc.com/timingfiles/latest-tools/ClockBuilder-Pro-README.pdf



Clock board configuration:
  To configure the skyworks Si5338 clock boards, you first need to download the clockbuilderpro software from: https://www.skyworksinc.com/Application-Pages/Clockbuilder-Pro-Software
  Then, to configure a board, connect it to the computer via USB, open the software app on the computer, and you should see an 'open default plan' button under a tab with ‘evaluation board detected’ as its title. Click this and you will get into the configuration menu. There will be a pop up asking to write the design, you can accept or deny, it will be overwritten anyways. Then on the drop down ‘design dashboard’ menu in the top left under the logo, go to steps five and six and configure them as in the screenshots called 'clock_board_1' and 'clock_board_2'. The output frequency values are variable and can be changed to your needs with the FCFD, but the rest should be kept as in the screenshots.

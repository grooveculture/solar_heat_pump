require('dotenv').config();
const { time } = require('console');
const puppeteer = require('puppeteer');
const { Sequelize } = require('sequelize');
const sequelize = new Sequelize(process.env.DB_DB, process.env.DB_USER, process.env.DB_PASS, {
    host: process.env.DB_HOST,
    dialect: process.env.DB_DIALECT,
    dialectOptions: {
        useUTC: false, //for reading from database
        dateStrings: true,
        typeCast: function (field, next) { // for reading from database
          if (field.type === 'DATETIME') {
            return field.string()
          }
            return next()
          },
      },
      timezone: '+00:00'
  });


const waitTillHTMLRendered = async (page, timeout = 30000) => {
    const checkDurationMsecs = 1000;
    const maxChecks = timeout / checkDurationMsecs;
    let lastHTMLSize = 0;
    let checkCounts = 1;
    let countStableSizeIterations = 0;
    const minStableSizeIterations = 3;

    while (checkCounts++ <= maxChecks) {
        let html = await page.content();
        let currentHTMLSize = html.length;

        //      let bodyHTMLSize = await page.evaluate(() => document.body.innerHTML.length);
        //      console.log('last: ', lastHTMLSize, ' <> curr: ', currentHTMLSize, " body html size: ", bodyHTMLSize);

        if (lastHTMLSize != 0 && currentHTMLSize == lastHTMLSize)
            countStableSizeIterations++;
        else
            countStableSizeIterations = 0; //reset the counter

        if (countStableSizeIterations >= minStableSizeIterations) {
//            console.log("Page rendered fully..");
            break;
        }

        lastHTMLSize = currentHTMLSize;
        //      await page.waitFor(checkDurationMsecs);
        await page.waitForTimeout(checkDurationMsecs);
    }
};


(async () => {

    const browser = await puppeteer.launch({ ignoreHTTPSErrors: true, acceptInsecureCerts: true, args: ['--proxy-bypass-list=*', '--disable-gpu', '--disable-dev-shm-usage', '--disable-setuid-sandbox', '--no-first-run', '--no-sandbox', '--no-zygote', '--single-process', '--ignore-certificate-errors', '--ignore-certificate-errors-spki-list', '--enable-features=NetworkService'] });

    page = await browser.newPage();
    await page.goto('https://portal.oventrop.com/sbus/scheme/id/zhK21_5qqXkcsDyGGyxNPNwasqVB_Ml6MCSyGtPrsLo', { waitUntil: 'load' });

    await waitTillHTMLRendered(page)
    const data = await page.content();
//    console.log(data);

    const newPage = await page.evaluate(() => {
//        return document.getElementById('value_00_0010_7351_0100-012_2_0').innerHTML;  
        return document.getElementById('value_00_0010_7351_0100-014_2_0').innerHTML; 
    });

    console.log(newPage.substring(0, 4));
    temp = (newPage.substring(0, 4));
    insertData(temp);
    await browser.close()

})();


async function insertData(){

    const sequelize = new Sequelize(process.env.DB_DB, process.env.DB_USER, process.env.DB_PASS, {
        host: process.env.DB_HOST,
        dialect: process.env.DB_DIALECT
      });

      const SpeicherTempBH = sequelize.define('oventrop_temp_bh', {
        temp: {
          type: Sequelize.DOUBLE,
          required: true,
          unique: false
        }
      })



      try {
        await sequelize.authenticate();
        console.log('Connection has been established successfully.');
      } catch (error) {
        console.error('Unable to connect to the database:', error);
      }
        

      var myobjs = [
        { temp: temp }
      ];

      sequelize.sync({ force: false })
      .then(() => {
        console.log(`Database & tables created!`);

        SpeicherTempBH.bulkCreate([
          myobjs[0]
        ]).then(function () {
          return SpeicherTempBH.findAll();
        }).then(function (oventrop_temp_bh) {
          console.log(oventrop_temp_bh);
        });
      });
}
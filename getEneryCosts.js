const puppeteer = require('puppeteer');

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
    await page.goto('https://kundencenter.elektra.ch/de/services/login.php', { waitUntil: 'load' });
    await page.type('#username', 'danielschaerer@protonmail.com');
    await page.type('#password', 'N^F7YQw3NBvR*eTybXTE6c');
    await page.click('#login');
    await page.goto('https://kundencenter.elektra.ch/de/services/verbrauch.php', { waitUntil: 'load' });
    await waitTillHTMLRendered(page)
    const data = await page.content();
//    console.log(data);

    const newPage = await page.evaluate(() => {
//        return document.getElementById('value_00_0010_7351_0100-014_2_0').innerHTML;  
        return document.getElementByClassName('no-more-tables elementTable_var0').innerHTML;  
    });

    console.log(newPage);
    // console.log(newPage.substring(0, 4));
    // temp = (newPage.substring(0, 4));
    // insertData(temp);
    await browser.close()

})();

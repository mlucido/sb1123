const fs = require('fs');
const content = fs.readFileSync('./listings.js', 'utf8');
const arrayMatch = content.match(/\[([\s\S]*)\];?$/);
const listings = JSON.parse('[' + arrayMatch[1] + ']');

// Southern SFV cities and their expected zip codes
const sfvZips = {
  'Van Nuys': ['91401', '91405', '91406', '91411', '91436'],
  'Sherman Oaks': ['91403', '91423'],
  'Encino': ['91316', '91436'],
  'Tarzana': ['91335', '91356'],
  'Woodland Hills': ['91364', '91367'],
  'Studio City': ['91604'],
  'Valley Village': ['91607'],
  'North Hollywood': ['91601', '91602', '91605', '91606'],
  'Reseda': ['91335']
};

const allExpectedZips = new Set([].concat(...Object.values(sfvZips)));

console.log('=== COVERAGE VALIDATION REPORT ===\n');

// Get all SFV listings
const sfvCities = Object.keys(sfvZips);
const sfvListings = listings.filter(l => sfvCities.includes(l.city));

console.log('1. COVERAGE OVERVIEW');
console.log(`Total SFV listings: ${sfvListings.length}`);
console.log(`Expected zip codes: ${allExpectedZips.size}`);
console.log(`Covered zip codes: ${new Set(sfvListings.map(l => l.zip)).size}`);

// Check for zip code coverage
console.log('\n2. ZIP CODE ANALYSIS');
const coveredZips = new Set(sfvListings.map(l => l.zip));
const missingZips = [...allExpectedZips].filter(z => !coveredZips.has(z));

if (missingZips.length > 0) {
  console.log(`⚠️  Missing zip codes (${missingZips.length}):`, missingZips.join(', '));
} else {
  console.log('✓ All expected zip codes covered');
}

// Analyze SB 1123 eligible properties
console.log('\n3. SB 1123 ELIGIBLE PROPERTIES');
const sb1123 = sfvListings.filter(l => 
  l.lotSf >= 12000 && 
  (l.type === 'Single Family Residential' || l.type === 'Vacant Land') &&
  l.fireZone === false
);

console.log(`Total eligible: ${sb1123.length}`);
console.log('\nBy city:');
sfvCities.forEach(city => {
  const count = sb1123.filter(l => l.city === city).length;
  const total = sfvListings.filter(l => l.city === city).length;
  const pct = total > 0 ? (count / total * 100).toFixed(1) : '0.0';
  console.log(`  ${city.padEnd(20)} ${count.toString().padStart(3)} / ${total.toString().padStart(4)} (${pct}%)`);
});

// Check data freshness
console.log('\n4. DATA QUALITY CHECKS');
const withDom = sfvListings.filter(l => l.dom != null);
const avgDom = withDom.reduce((sum, l) => sum + l.dom, 0) / withDom.length;
console.log(`Listings with DOM data: ${withDom.length} / ${sfvListings.length}`);
console.log(`Average days on market: ${avgDom.toFixed(0)}`);

// Check for stale listings
const staleListing = sfvListings.filter(l => l.dom > 180);
console.log(`Listings > 180 days old: ${staleListing.length}`);

// Property type breakdown
console.log('\n5. PROPERTY TYPE BREAKDOWN (SB 1123 Eligible)');
const typeBreakdown = {};
sb1123.forEach(l => {
  typeBreakdown[l.type] = (typeBreakdown[l.type] || 0) + 1;
});
Object.entries(typeBreakdown).forEach(([type, count]) => {
  console.log(`  ${type}: ${count}`);
});

// Lot size distribution
console.log('\n6. LOT SIZE DISTRIBUTION (SB 1123 Eligible)');
const lotSizes = sb1123.map(l => l.lotSf).sort((a, b) => a - b);
console.log(`  Min: ${lotSizes[0].toLocaleString()} SF`);
console.log(`  Median: ${lotSizes[Math.floor(lotSizes.length / 2)].toLocaleString()} SF`);
console.log(`  Max: ${lotSizes[lotSizes.length - 1].toLocaleString()} SF`);

// Price range
console.log('\n7. PRICE RANGE (SB 1123 Eligible)');
const prices = sb1123.filter(l => l.price > 0).map(l => l.price).sort((a, b) => a - b);
if (prices.length > 0) {
  console.log(`  Min: $${prices[0].toLocaleString()}`);
  console.log(`  Median: $${prices[Math.floor(prices.length / 2)].toLocaleString()}`);
  console.log(`  Max: $${prices[prices.length - 1].toLocaleString()}`);
}

// Sample high-value targets
console.log('\n8. HIGH-VALUE ACQUISITION TARGETS (Top 10 by Lot Size)');
const topTargets = sb1123
  .filter(l => l.price > 0)
  .sort((a, b) => b.lotSf - a.lotSf)
  .slice(0, 10);

topTargets.forEach((l, i) => {
  console.log(`${(i + 1).toString().padStart(2)}. ${l.address}`);
  console.log(`    ${l.lotSf.toLocaleString()} SF lot | $${l.price.toLocaleString()} | ${l.city}`);
  console.log(`    ${l.url}`);
});

console.log('\n=== VALIDATION SUMMARY ===');
console.log(`✓ Coverage area defined: ${sfvCities.length} cities`);
console.log(`✓ Total listings captured: ${sfvListings.length}`);
console.log(`✓ SB 1123 eligible properties: ${sb1123.length}`);
console.log(`${missingZips.length > 0 ? '⚠️' : '✓'} Zip code coverage: ${coveredZips.size} / ${allExpectedZips.size}`);

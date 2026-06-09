#!/usr/bin/env python3
"""
ServiceNow AD Group Request Automation - Batch Version
Automates the process of raising AD group membership requests via ServiceNow portal.
This version processes MULTIPLE GROUPS - creates ONE request per group, adding all users to each group.

Usage:
    python ad_group_batch.py --groups "GROUP1,GROUP2,GROUP3" --users "user1,user2" --justification "Business reason"
"""

import argparse
import time
import sys
from typing import List
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException


class ServiceNowADAutomation:
    """Automates AD group membership requests on ServiceNow."""

    SERVICENOW_URL = "https://walmartglobal.service-now.com/wm_sp"
    DEFAULT_TIMEOUT = 30

    def __init__(self, headless: bool = False, timeout: int = DEFAULT_TIMEOUT):
        """
        Initialize the automation driver.

        Args:
            headless: Run browser in headless mode (no UI)
            timeout: Default wait timeout in seconds
        """
        self.timeout = timeout
        self.driver = self._setup_driver(headless)
        self.wait = WebDriverWait(self.driver, timeout)

    def _setup_driver(self, headless: bool) -> webdriver.Chrome:
        """Configure and return Chrome WebDriver."""
        options = Options()

        if headless:
            options.add_argument("--headless=new")

        # Common options for stability
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-extensions")

        # Walmart SSO may require these
        options.add_argument("--disable-web-security")
        options.add_argument("--allow-running-insecure-content")

        try:
            driver = webdriver.Chrome(options=options)
            return driver
        except Exception as e:
            print(f"❌ Failed to initialize Chrome driver: {e}")
            print("💡 Make sure ChromeDriver is installed: brew install chromedriver")
            sys.exit(1)

    def wait_and_click(self, by: By, value: str, description: str = "element"):
        """Wait for element to be clickable and click it."""
        try:
            print(f"  ⏳ Waiting for {description}...")
            element = self.wait.until(EC.element_to_be_clickable((by, value)))
            element.click()
            print(f"  ✅ Clicked {description}")
            time.sleep(1)  # Brief pause for UI to update
            return element
        except TimeoutException:
            print(f"  ❌ Timeout waiting for {description}")
            raise

    def wait_and_type(self, by: By, value: str, text: str, description: str = "field"):
        """Wait for input field and type text."""
        try:
            print(f"  ⏳ Waiting for {description}...")
            element = self.wait.until(EC.presence_of_element_located((by, value)))
            element.clear()
            element.send_keys(text)
            print(f"  ✅ Entered text in {description}")
            time.sleep(0.5)
            return element
        except TimeoutException:
            print(f"  ❌ Timeout waiting for {description}")
            raise

    def select_from_dropdown(self, search_text: str, description: str = "item"):
        """Type in search field and select from dropdown results."""
        time.sleep(1)  # Wait for dropdown to populate
        try:
            # Look for dropdown option containing the search text
            dropdown_item = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, f"//*[contains(text(), '{search_text}')]"))
            )
            dropdown_item.click()
            print(f"  ✅ Selected {description}: {search_text}")
            time.sleep(0.5)
        except TimeoutException:
            print(f"  ⚠️ Could not find exact match for {search_text}, trying partial match...")
            # Try clicking first available option
            try:
                first_option = self.driver.find_element(By.CSS_SELECTOR, ".dropdown-item, .ui-menu-item, [role='option']")
                first_option.click()
            except NoSuchElementException:
                print(f"  ❌ No dropdown options found for {search_text}")
                raise

    def navigate_to_servicenow(self):
        """Open ServiceNow portal and wait for page load."""
        print("\n🌐 Opening ServiceNow portal...")
        self.driver.get(self.SERVICENOW_URL)

        # Wait for SSO redirect and page load
        print("  ⏳ Waiting for SSO authentication (you may need to log in manually)...")

        # Wait up to 120 seconds for manual SSO login if needed
        try:
            self.wait = WebDriverWait(self.driver, 120)
            # Wait until we're on the ServiceNow page (not SSO)
            self.wait.until(lambda d: "service-now.com" in d.current_url and "login" not in d.current_url.lower())
            print("  ✅ Successfully authenticated to ServiceNow")
        except TimeoutException:
            print("  ❌ SSO authentication timeout. Please complete login manually.")
            raise
        finally:
            # Reset to normal timeout
            self.wait = WebDriverWait(self.driver, self.timeout)

    def select_dropdown_option(self, dropdown_label: str, option_text: str):
        """
        Select an option from a ServiceNow Select2 dropdown.
        Uses AngularJS-aware approach to properly trigger cascading dropdowns.

        Args:
            dropdown_label: Partial text of the dropdown label/question
            option_text: The option text to select
        """
        print(f"  ⏳ Selecting '{option_text}' for '{dropdown_label[:40]}...'")

        # ServiceNow uses AngularJS + Select2. We need to:
        # 1. Find the select element by its ID (derived from the Select2 container)
        # 2. Set the value on the underlying select
        # 3. Trigger AngularJS digest cycle to update cascading dropdowns
        script = f"""
        (function() {{
            var dropdownLabel = '{dropdown_label}';
            var optionText = '{option_text}';

            // Find the Select2 focusser input by aria-label
            var inputs = document.querySelectorAll('input.select2-focusser');
            var selectElement = null;
            var selectId = null;

            for (var i = 0; i < inputs.length; i++) {{
                var label = inputs[i].getAttribute('aria-label');
                if (label && label.includes(dropdownLabel)) {{
                    var container = inputs[i].closest('.select2-container');
                    if (container) {{
                        // The select ID is the container ID minus 's2id_'
                        selectId = container.id.replace('s2id_', '');
                        selectElement = document.getElementById(selectId);
                        break;
                    }}
                }}
            }}

            if (!selectElement) {{
                return {{'success': false, 'error': 'Could not find select element for: ' + dropdownLabel}};
            }}

            // Find the option value that matches the text
            var optionValue = null;
            var optionFullText = null;
            for (var i = 0; i < selectElement.options.length; i++) {{
                var opt = selectElement.options[i];
                if (opt.text && opt.text.includes(optionText)) {{
                    optionValue = opt.value;
                    optionFullText = opt.text;
                    break;
                }}
            }}

            if (optionValue === null) {{
                return {{'success': false, 'error': 'Could not find option: ' + optionText}};
            }}

            // Set the value on the native select element
            selectElement.value = optionValue;

            // Get AngularJS scope and update the model
            var $select = angular.element(selectElement);
            var scope = $select.scope();

            if (scope) {{
                // Update the field value through Angular
                scope.$apply(function() {{
                    // The ng-model is "fieldValue" with getterSetter option
                    // We need to call the setter
                    if (typeof scope.fieldValue === 'function') {{
                        scope.fieldValue(optionValue);
                    }} else {{
                        scope.fieldValue = optionValue;
                    }}
                }});
            }}

            // Also trigger Select2 update for UI
            if (typeof jQuery !== 'undefined') {{
                jQuery(selectElement).val(optionValue).trigger('change');
            }}

            // Dispatch native events
            selectElement.dispatchEvent(new Event('change', {{ bubbles: true }}));
            selectElement.dispatchEvent(new Event('input', {{ bubbles: true }}));

            return {{'success': true, 'selectedText': optionFullText, 'selectedValue': optionValue, 'selectId': selectId}};
        }})();
        """

        try:
            result = self.driver.execute_script(script)

            # Handle None result
            if result is None:
                result = {'success': False, 'error': 'Script returned None - jQuery may not be available'}

            if result.get('success'):
                print(f"  ✅ Selected '{result.get('selectedText', option_text)}'")
                time.sleep(0.5)  # Brief wait for cascading dropdowns
                return  # Success, exit early
            else:
                error = result.get('error', 'Unknown error')
                print(f"  ⚠️ Select2 API method failed: {error}")

                # Fallback: Try simulating actual click interaction
                print(f"  ⏳ Trying click-based selection...")

                # Click to open dropdown
                open_script = f"""
                var inputs = document.querySelectorAll('input.select2-focusser');
                for (var i = 0; i < inputs.length; i++) {{
                    var label = inputs[i].getAttribute('aria-label');
                    if (label && label.includes('{dropdown_label}')) {{
                        var container = inputs[i].closest('.select2-container');
                        var choice = container.querySelector('.select2-choice, .select2-chosen');
                        if (choice) {{
                            choice.click();
                            return true;
                        }}
                    }}
                }}
                return false;
                """
                self.driver.execute_script(open_script)
                time.sleep(1)

                # Click the option - look in the active dropdown only
                click_script = f"""
                // Look for the active/visible Select2 dropdown
                var dropdowns = document.querySelectorAll('.select2-drop');
                var activeDropdown = null;
                for (var i = 0; i < dropdowns.length; i++) {{
                    if (dropdowns[i].style.display !== 'none' &&
                        !dropdowns[i].classList.contains('select2-display-none')) {{
                        activeDropdown = dropdowns[i];
                        break;
                    }}
                }}

                if (!activeDropdown) {{
                    // Try finding by active class
                    activeDropdown = document.querySelector('.select2-drop-active, .select2-with-searchbox');
                }}

                if (activeDropdown) {{
                    var results = activeDropdown.querySelectorAll('.select2-result-label, li.select2-result');
                    for (var i = 0; i < results.length; i++) {{
                        var text = results[i].textContent.trim();
                        // Exact match for simple options
                        if (text === '{option_text}') {{
                            results[i].click();
                            return {{'clicked': true, 'text': text}};
                        }}
                    }}
                    // Try partial match as fallback
                    for (var i = 0; i < results.length; i++) {{
                        var text = results[i].textContent.trim();
                        if (text.includes('{option_text}')) {{
                            results[i].click();
                            return {{'clicked': true, 'text': text}};
                        }}
                    }}
                }}
                return {{'clicked': false, 'dropdownFound': !!activeDropdown}};
                """
                click_result = self.driver.execute_script(click_script)

                if click_result and click_result.get('clicked'):
                    print(f"  ✅ Selected '{click_result.get('text')}' via click")
                    time.sleep(0.5)
                    return  # Success
                else:
                    # One more try - use Selenium to find and click
                    try:
                        dropdown_option = WebDriverWait(self.driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH,
                                f"//div[contains(@class, 'select2-result-label')][text()='{option_text}']"
                            ))
                        )
                        dropdown_option.click()
                        print(f"  ✅ Selected '{option_text}' via Selenium")
                        time.sleep(2)
                        return  # Success
                    except:
                        # Check if value was selected despite script issues
                        verify_script = f"""
                        var inputs = document.querySelectorAll('input.select2-focusser');
                        for (var i = 0; i < inputs.length; i++) {{
                            var label = inputs[i].getAttribute('aria-label');
                            if (label && label.includes('{dropdown_label}')) {{
                                var container = inputs[i].closest('.select2-container');
                                var chosen = container.querySelector('.select2-chosen');
                                if (chosen && chosen.textContent.includes('{option_text}')) {{
                                    return true;
                                }}
                            }}
                        }}
                        return false;
                        """
                        if self.driver.execute_script(verify_script):
                            print(f"  ✅ Verified '{option_text}' is selected")
                            time.sleep(0.5)
                            return  # Success
                        raise Exception(f"Could not select '{option_text}'")

        except Exception as e:
            print(f"  ❌ Failed to select option: {e}")
            raise

    def navigate_to_ad_request(self, num_groups: int = 1):
        """
        Navigate through ServiceNow to AD Group request form.
        Uses dropdown-based UI (as of 2024).

        Args:
            num_groups: Number of groups being requested (affects One/Multiple selection)
        """
        print("\n📋 Navigating to AD Group request form...")

        # Step 1: Click on Active Directory in the services menu
        ad_selectors = [
            (By.XPATH, "//*[contains(text(), 'Active Directory')]"),
            (By.LINK_TEXT, "Active Directory"),
            (By.PARTIAL_LINK_TEXT, "Active Directory"),
            (By.CSS_SELECTOR, "[data-item-name='Active Directory']"),
        ]

        for by, selector in ad_selectors:
            try:
                self.wait_and_click(by, selector, "Active Directory option")
                break
            except:
                continue

        time.sleep(2)

        # Wait for the form to fully load
        print("\n  ⏳ Waiting for form to load...")
        try:
            # Wait for either a Select2 dropdown or a form element to appear
            WebDriverWait(self.driver, 30).until(
                lambda d: len(d.find_elements(By.CSS_SELECTOR, ".select2-container, select, .form-group")) > 0
            )
            print("  ✅ Form loaded")
        except:
            print("  ⚠️ Form may not have fully loaded, continuing anyway...")
        time.sleep(2)

        # Step 2: Fill out the "Describe Needs" form with dropdowns
        # Using shorter waits since cascading dropdowns load quickly
        print("\n📝 Filling out Describe Needs form...")

        # Dropdown 1: Environment = Production
        self.select_dropdown_option("What environment are you requesting", "Production")

        # Dropdown 2: Type = Group
        self.select_dropdown_option("What type of Active Directory activity", "Group")

        # Dropdown 3: Action = Modify an existing Active Directory group
        self.select_dropdown_option("What are you looking to do with", "Modify an existing Active Directory group")

        # Dropdown 4: What to modify = Group Membership
        self.select_dropdown_option("What are you looking to modify", "Group Membership")

        # Dropdown 5: One or Multiple Groups
        if num_groups > 1:
            self.select_dropdown_option("Are you looking to modify one", "Multiple Groups")
        else:
            self.select_dropdown_option("Are you looking to modify one", "One Group")

        # Click Next to proceed to Choose Options
        # The Next button has id="submit" and text "next" (lowercase), uses ng-click="goNext()"
        print("\n  ⏳ Looking for Next button...")

        try:
            # Primary method: Find by ID (most reliable)
            next_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "submit"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView(true);", next_btn)
            time.sleep(0.3)
            next_btn.click()
            print("  ✅ Clicked Next button (by ID)")
        except:
            # Fallback: Try via AngularJS scope
            try:
                script = """
                var btn = document.getElementById('submit');
                if (btn) {
                    // Try clicking directly
                    btn.click();
                    return true;
                }
                // Alternative: trigger ng-click via Angular
                var scope = angular.element(document.body).scope();
                if (scope && scope.goNext) {
                    scope.$apply(function() { scope.goNext(); });
                    return true;
                }
                return false;
                """
                result = self.driver.execute_script(script)
                if result:
                    print("  ✅ Clicked Next button via JavaScript")
                else:
                    print("  ⚠️ Could not find Next button")
            except Exception as e:
                print(f"  ⚠️ Next button click failed: {e}")

        # Wait for page 2 to load
        time.sleep(3)
        print("  ✅ Navigated to Choose Options page")

    def enable_toggle_if_needed(self, toggle_text: str):
        """Enable a toggle switch if it exists and is not already enabled."""
        try:
            # Find toggle by nearby text
            toggle_selectors = [
                f"//*[contains(text(), '{toggle_text}')]/ancestor::*[contains(@class, 'toggle') or contains(@class, 'switch')]//input",
                f"//*[contains(text(), '{toggle_text}')]/following::*[contains(@class, 'toggle') or contains(@class, 'switch')][1]",
                f"//*[contains(text(), '{toggle_text}')]/ancestor::div[contains(@class, 'item')]//input[@type='checkbox']",
            ]

            for selector in toggle_selectors:
                try:
                    toggle = self.driver.find_element(By.XPATH, selector)
                    if toggle:
                        # Check if already enabled
                        if not toggle.is_selected():
                            toggle.click()
                            print(f"  ✅ Enabled toggle: {toggle_text}")
                        else:
                            print(f"  ✅ Toggle already enabled: {toggle_text}")
                        return True
                except:
                    continue

            # Try clicking the toggle container itself
            toggle_container = self.driver.find_element(
                By.XPATH,
                f"//*[contains(text(), '{toggle_text}')]/ancestor::*[contains(@class, 'included-item') or contains(@class, 'toggle-container')]"
            )
            toggle_container.click()
            print(f"  ✅ Clicked toggle area: {toggle_text}")
            return True

        except Exception as e:
            print(f"  ⚠️ Could not find/enable toggle '{toggle_text}': {e}")
            return False

    def add_group_chip(self, group_name: str):
        """
        Add a group to the groups input field (creates a chip/tag).
        Uses exact element IDs: sp_formfield_group_list, s2id_sp_formfield_group_list
        This is a multi-select field.
        """
        try:
            print(f"  ⏳ Adding group: {group_name}")

            # The groups field is a Select2 multi-select
            # Container ID: s2id_sp_formfield_group_list
            # Underlying select ID: sp_formfield_group_list

            # Click on the Select2 container to open/focus it
            script = """
            (function() {
                var container = document.getElementById('s2id_sp_formfield_group_list');
                if (!container) {
                    return {'success': false, 'error': 'Groups field container not found'};
                }

                // For multi-select, click the input area
                var input = container.querySelector('input.select2-input');
                if (input) {
                    input.focus();
                    input.click();
                    return {'success': true, 'action': 'focused', 'inputFound': true};
                }

                // Alternative: click the choices container
                var choices = container.querySelector('.select2-choices');
                if (choices) {
                    choices.click();
                    return {'success': true, 'action': 'clicked choices'};
                }

                return {'success': false, 'error': 'Could not find input element'};
            })();
            """
            result = self.driver.execute_script(script)

            if not result or not result.get('success'):
                # Fallback: Try Selenium
                try:
                    container = self.wait.until(EC.element_to_be_clickable((By.ID, "s2id_sp_formfield_group_list")))
                    container.click()
                except:
                    pass

            time.sleep(0.5)

            # Type the group name in the search field
            try:
                # For multi-select, the input is inside the container
                search_input = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR,
                        "#s2id_sp_formfield_group_list input.select2-input, .select2-drop-active input.select2-input"))
                )
                search_input.clear()
                search_input.send_keys(group_name)
                time.sleep(1.5)  # Wait for autocomplete results

                # Click on the matching result
                result_selector = f"//div[contains(@class, 'select2-result-label')][contains(text(), '{group_name}')]"
                try:
                    result_item = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, result_selector))
                    )
                    result_item.click()
                    print(f"  ✅ Added group: {group_name}")
                except:
                    # Try clicking first result (it should match)
                    first_result = self.driver.find_element(By.CSS_SELECTOR, ".select2-results li.select2-result-selectable")
                    first_result.click()
                    print(f"  ✅ Added first matching group for: {group_name}")

            except Exception as e:
                print(f"  ⚠️ Search input method failed: {e}")
                raise

            time.sleep(0.5)

        except Exception as e:
            print(f"  ❌ Failed to add group {group_name}: {e}")
            raise

    def select_user_to_modify(self, username: str):
        """
        Select the user to modify in the 'User to modify' field.
        Uses exact element IDs: sp_formfield_user_reference, s2id_sp_formfield_user_reference
        """
        try:
            print(f"  ⏳ Selecting user: {username}")

            # The user field is a Select2 reference field
            # Container ID: s2id_sp_formfield_user_reference
            # Hidden input ID: sp_formfield_user_reference
            # Search input inside the dropdown

            # Click on the Select2 container to open the dropdown
            script = """
            (function() {
                var container = document.getElementById('s2id_sp_formfield_user_reference');
                if (!container) {
                    return {'success': false, 'error': 'User field container not found'};
                }

                // Click the choice link to open dropdown
                var choice = container.querySelector('a.select2-choice');
                if (choice) {
                    choice.click();
                    return {'success': true, 'action': 'opened'};
                }

                return {'success': false, 'error': 'Could not find choice element'};
            })();
            """
            result = self.driver.execute_script(script)

            if not result or not result.get('success'):
                # Fallback: Try Selenium click
                try:
                    container = self.wait.until(EC.element_to_be_clickable((By.ID, "s2id_sp_formfield_user_reference")))
                    container.click()
                except:
                    pass

            time.sleep(0.5)

            # Now type in the search field that appears
            try:
                # The search input appears in the dropdown
                search_input = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".select2-drop-active input.select2-input, #select2-drop input.select2-input"))
                )
                search_input.clear()
                search_input.send_keys(username)
                time.sleep(1.5)  # Wait for autocomplete results

                # Click on the matching result
                result_selector = f"//div[contains(@class, 'select2-result-label')][contains(text(), '{username}')]"
                try:
                    result_item = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, result_selector))
                    )
                    result_item.click()
                    print(f"  ✅ Selected user: {username}")
                except:
                    # Try clicking the first result
                    first_result = self.driver.find_element(By.CSS_SELECTOR, ".select2-results li.select2-result-selectable")
                    first_result.click()
                    print(f"  ✅ Selected first matching user for: {username}")

            except Exception as e:
                print(f"  ⚠️ Search input method failed: {e}")
                # Fallback: Try direct API approach
                fallback_script = f"""
                (function() {{
                    var hiddenInput = document.getElementById('sp_formfield_user_reference');
                    if (hiddenInput) {{
                        // For reference fields, we need to use ServiceNow's g_form API if available
                        // or trigger the Select2 API
                        var $container = jQuery('#s2id_sp_formfield_user_reference');
                        if ($container.length) {{
                            $container.select2('open');
                            return {{'success': true, 'note': 'Opened via Select2 API'}};
                        }}
                    }}
                    return {{'success': false}};
                }})();
                """
                self.driver.execute_script(fallback_script)
                raise

            time.sleep(0.5)

        except Exception as e:
            print(f"  ❌ Failed to select user {username}: {e}")
            raise

    def click_accordion_item(self, item_text: str):
        """
        Click on an accordion item to expand it and reveal form fields.
        ServiceNow uses uib-accordion. Need to click the panel-heading row to expand.
        First checks if already expanded.

        Args:
            item_text: Partial text of the accordion item to click (e.g., "Modify Active Directory")
        """
        print(f"  ⏳ Checking accordion: {item_text[:40]}...")

        # First check if accordion is already expanded
        check_script = """
        (function() {
            // Check if panel-collapse has 'in' class (expanded) and aria-expanded="true"
            var panels = document.querySelectorAll('.panel-collapse');
            for (var i = 0; i < panels.length; i++) {
                if (panels[i].classList.contains('in') || panels[i].getAttribute('aria-expanded') === 'true') {
                    // Check if form fields are visible inside
                    var fields = panels[i].querySelectorAll('#sp_formfield_busjust, #s2id_sp_formfield_user_reference, [id*="sp_formfield"]');
                    if (fields.length > 0) {
                        return {'expanded': true, 'fieldsFound': fields.length};
                    }
                }
            }
            return {'expanded': false};
        })();
        """
        try:
            check_result = self.driver.execute_script(check_script)
            if check_result and check_result.get('expanded'):
                print(f"  ✅ Accordion already expanded ({check_result.get('fieldsFound', 0)} fields visible)")
                return True
        except:
            pass

        # First, try to click using JavaScript - find the row containing the text and click it
        script = f"""
        (function() {{
            // Look for the accordion row containing the item text
            // The structure is: panel-heading > panel-title > accordion-toggle > row with item name

            // Method 1: Find by item_name ID and click the accordion-toggle parent
            var itemNames = document.querySelectorAll('[id^="item_name_"]');
            for (var i = 0; i < itemNames.length; i++) {{
                var text = itemNames[i].textContent || itemNames[i].innerText;
                if (text.includes('{item_text}')) {{
                    // Find the accordion-toggle div (has ng-click="toggleOpen()")
                    var toggle = itemNames[i].closest('.accordion-toggle');
                    if (toggle) {{
                        toggle.click();
                        return {{'success': true, 'method': 'accordion-toggle', 'text': text.trim().substring(0, 50)}};
                    }}
                    // Try panel-heading
                    var heading = itemNames[i].closest('.panel-heading');
                    if (heading) {{
                        heading.click();
                        return {{'success': true, 'method': 'panel-heading', 'text': text.trim().substring(0, 50)}};
                    }}
                }}
            }}

            // Method 2: Find the row with "Options" text and click it
            var rows = document.querySelectorAll('.row[role="button"], div[ng-click="showCancel"]');
            for (var i = 0; i < rows.length; i++) {{
                var text = rows[i].textContent || rows[i].innerText;
                if (text.includes('{item_text}')) {{
                    rows[i].click();
                    return {{'success': true, 'method': 'row-button', 'text': text.trim().substring(0, 50)}};
                }}
            }}

            // Method 3: Click the chevron icon directly
            var chevrons = document.querySelectorAll('.fa-chevron-down, .accordion-icon');
            for (var i = 0; i < chevrons.length; i++) {{
                var container = chevrons[i].closest('[ng-repeat*="includedItems"], .panel');
                if (container) {{
                    var text = container.textContent || '';
                    if (text.includes('{item_text}')) {{
                        // Click the parent that has the ng-click
                        var clickable = chevrons[i].closest('[ng-click]') || chevrons[i].parentElement;
                        if (clickable) clickable.click();
                        else chevrons[i].click();
                        return {{'success': true, 'method': 'chevron'}};
                    }}
                }}
            }}

            return {{'success': false, 'error': 'Accordion element not found'}};
        }})();
        """

        try:
            result = self.driver.execute_script(script)
            if result and result.get('success'):
                print(f"  ✅ Clicked accordion ({result.get('method', 'js')})")
                time.sleep(0.8)  # Wait for accordion animation
                return True
        except Exception as e:
            print(f"  ⚠️ JS click failed: {e}")

        # Fallback: Use Selenium to click
        try:
            # Try clicking the panel-heading that contains our text
            accordion = WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((
                By.XPATH, f"//*[contains(text(), '{item_text}')]/ancestor::div[contains(@class, 'panel-heading')]"
            )))
            self.driver.execute_script("arguments[0].scrollIntoView(true);", accordion)
            time.sleep(0.2)
            accordion.click()
            print(f"  ✅ Expanded accordion via Selenium")
            time.sleep(0.8)
            return True
        except:
            pass

        # Last resort: Click the "Options" link
        try:
            options_link = self.driver.find_element(By.XPATH,
                f"//*[contains(text(), '{item_text}')]/ancestor::*[contains(@class, 'panel')]//span[contains(text(), 'Options')]"
            )
            options_link.click()
            print(f"  ✅ Expanded via Options link")
            time.sleep(0.8)
            return True
        except:
            print(f"  ❌ Could not expand accordion")
            return False

    def select_group_name_field(self, group_name: str):
        """
        Select group in 'Group name' field (GROUP-centric form).
        This is the first field - a dropdown to search and select the AD group.
        """
        print(f"  ⏳ Selecting group: {group_name}")

        try:
            # Find the Group name dropdown using Selenium directly
            # Look for the Select2 container near the "Group name" label
            group_dropdown = None

            # Method 1: Find by XPath near label
            try:
                group_dropdown = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH,
                        "//*[contains(text(), 'Group name')]/ancestor::div[contains(@class, 'form-group')]//a[contains(@class, 'select2-choice')]"))
                )
            except:
                pass

            # Method 2: Find first select2-choice on the page
            if not group_dropdown:
                try:
                    group_dropdown = WebDriverWait(self.driver, 3).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, ".select2-choice"))
                    )
                except:
                    pass

            if group_dropdown:
                # Scroll into view and click
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", group_dropdown)
                time.sleep(0.2)
                group_dropdown.click()
                time.sleep(0.5)

            # Type in the search input that appears
            search_input = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    ".select2-drop-active input.select2-input, .select2-search input, .select2-drop input"))
            )
            search_input.clear()
            search_input.send_keys(group_name)
            time.sleep(1.5)  # Wait for autocomplete

            # Click matching result
            try:
                result_item = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR,
                        ".select2-results li.select2-result-selectable"))
                )
                result_item.click()
                print(f"  ✅ Selected group: {group_name}")
            except:
                search_input.send_keys(Keys.RETURN)
                print(f"  ✅ Selected group via Enter: {group_name}")

            time.sleep(0.5)  # Wait for Group Description to populate

        except Exception as e:
            print(f"  ❌ Failed to select group: {e}")
            raise

    def fill_page2_group_centric_form(self, group_name: str, usernames: List[str], justification: str):
        """
        Fill Page 2 form which is GROUP-centric (when selecting "One Group"):
        1. Group name - dropdown to select the AD group
        2. Group Description - read-only (auto-populated)
        3. Choose members to add to or remove from the group - multi-select for users (SUPPORTS MULTIPLE!)
        4. Do you want to add the users or delete the users - dropdown
        5. Business Justification - text input

        Args:
            group_name: The AD group name
            usernames: List of usernames to add (can be single or multiple)
            justification: Business justification text
        """
        # Handle both single username (string) and list of usernames for backward compatibility
        if isinstance(usernames, str):
            usernames = [usernames]
        # Step 1: Select Group name (first Select2 dropdown)
        print(f"\n📂 Selecting group: {group_name}")
        try:
            # Find the first Select2 dropdown (Group name field)
            group_dropdown = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".select2-choice"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", group_dropdown)
            time.sleep(0.3)
            group_dropdown.click()
            time.sleep(0.8)

            # Type in the search input that appears
            search_input = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".select2-drop-active input.select2-input"))
            )
            self.driver.execute_script("""
                var input = arguments[0];
                input.focus();
                input.value = arguments[1];
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}));
            """, search_input, group_name)
            time.sleep(2)  # Wait for autocomplete results

            # Click result using JavaScript (more reliable than Selenium click)
            click_result = self.driver.execute_script("""
                var results = document.querySelectorAll('.select2-results li.select2-result-selectable');
                if (results.length > 0) {
                    results[0].click();
                    return {success: true, count: results.length};
                }
                return {success: false, count: 0};
            """)

            if click_result and click_result.get('success'):
                print(f"  ✅ Selected group: {group_name}")
            else:
                # Fallback: use keyboard, then dismiss mask
                search_input.send_keys(Keys.RETURN)
                print(f"  ✅ Selected group via Enter: {group_name}")

            time.sleep(1)  # Wait for Group Description to populate

            # CRITICAL: Dismiss any lingering select2-drop-mask
            self.driver.execute_script("""
                var mask = document.getElementById('select2-drop-mask');
                if (mask) {
                    mask.style.display = 'none';
                    mask.remove();
                }
                // Also close any open dropdowns
                var drops = document.querySelectorAll('.select2-drop-active');
                drops.forEach(function(d) { d.classList.remove('select2-drop-active'); });
            """)
            time.sleep(0.3)

        except Exception as e:
            print(f"  ❌ Failed to select group: {e}")
            raise

        # Step 2: Add ALL members to "Choose members" multi-select (one by one)
        print(f"\n👥 Adding {len(usernames)} member(s) to the group...")

        for i, username in enumerate(usernames, 1):
            print(f"\n  [{i}/{len(usernames)}] Adding member: {username}")
            try:
                # Find the multi-select container for members
                member_input = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".select2-container-multi input.select2-input"))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", member_input)
                time.sleep(0.3)
                member_input.click()
                time.sleep(0.3)

                # Type the username
                self.driver.execute_script("""
                    var input = arguments[0];
                    input.focus();
                    input.value = arguments[1];
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                    input.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}));
                """, member_input, username)
                time.sleep(1.5)

                # Click result
                try:
                    result = WebDriverWait(self.driver, 8).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, ".select2-results li.select2-result-selectable"))
                    )
                    result.click()
                    print(f"    ✅ Added member: {username}")
                except:
                    member_input.send_keys(Keys.RETURN)
                    print(f"    ✅ Added member via Enter: {username}")
                time.sleep(0.5)
            except Exception as e:
                print(f"    ❌ Failed to add member {username}: {e}")
                # Continue with remaining users instead of failing completely
                continue

        # Verify members were added
        print(f"\n  📋 Verifying added members...")
        try:
            chips = self.driver.find_elements(By.CSS_SELECTOR, ".select2-container-multi .select2-search-choice")
            print(f"  ✅ {len(chips)} member(s) added to the request")
        except:
            pass

        # Step 3: Select "Add users" from add/remove dropdown
        print("\n🔧 Setting action to 'Add users'...")
        try:
            self.select_dropdown_option("Do you want to add the users", "Add")
        except Exception as e:
            print(f"  ⚠️ Add/Remove dropdown failed: {e}, trying direct method...")
            # Try direct JavaScript - look for any addremove field
            script = """
            var selects = document.querySelectorAll('select[name*="addremove"]');
            for (var i = 0; i < selects.length; i++) {
                var select = selects[i];
                // Find option that contains 'add'
                for (var j = 0; j < select.options.length; j++) {
                    if (select.options[j].text.toLowerCase().includes('add')) {
                        select.value = select.options[j].value;
                        var $select = angular.element(select);
                        var scope = $select.scope();
                        if (scope) {
                            scope.$apply(function() {
                                if (typeof scope.fieldValue === 'function') scope.fieldValue(select.value);
                                else scope.fieldValue = select.value;
                            });
                        }
                        if (typeof jQuery !== 'undefined') jQuery(select).trigger('change');
                        select.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                    }
                }
            }
            return false;
            """
            self.driver.execute_script(script)
            print("  ✅ Set action via JavaScript")
        time.sleep(0.5)

        # Step 4: Enter business justification
        print(f"\n📝 Entering justification: {justification[:40]}...")
        try:
            # Find Business Justification input by label or ID pattern
            justification_input = None
            try:
                justification_input = self.driver.find_element(By.ID, "sp_formfield_busjust")
            except:
                # Try finding by label
                script = """
                var labels = document.querySelectorAll('label');
                for (var i = 0; i < labels.length; i++) {
                    if (labels[i].textContent.includes('Business Justification')) {
                        var formGroup = labels[i].closest('.form-group');
                        if (formGroup) {
                            var input = formGroup.querySelector('input[type="text"], textarea');
                            return input;
                        }
                    }
                }
                return null;
                """
                justification_input = self.driver.execute_script(script)

            if justification_input:
                justification_input.clear()
                justification_input.send_keys(justification)
                print("  ✅ Entered business justification")
            else:
                print("  ⚠️ Could not find justification field")
        except Exception as e:
            print(f"  ⚠️ Failed to enter justification: {e}")

        time.sleep(0.5)

    def select_group_name_dropdown(self, group_name: str):
        """
        Select group in 'Group name' dropdown (GROUP-centric form).
        This is a Select2 single-select dropdown.
        """
        print(f"  ⏳ Selecting group: {group_name}")

        try:
            # Find and click the first Select2 choice (Group name dropdown)
            dropdown = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".select2-choice"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", dropdown)
            time.sleep(0.2)
            dropdown.click()
            time.sleep(0.8)  # Wait for dropdown to fully open

            # Wait for the search input to be interactable
            search_input = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR,
                    ".select2-drop-active input.select2-input, .select2-search input.select2-input"))
            )

            # Use JavaScript to set value for reliability
            self.driver.execute_script("""
                var input = arguments[0];
                input.focus();
                input.value = arguments[1];
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
            """, search_input, group_name)
            time.sleep(2)  # Wait for autocomplete results

            # Click matching result
            try:
                result_item = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR,
                        ".select2-results li.select2-result-selectable"))
                )
                result_item.click()
                print(f"  ✅ Selected group: {group_name}")
            except:
                # Fallback: use keyboard
                search_input.send_keys(Keys.RETURN)
                print(f"  ✅ Selected group via Enter: {group_name}")

            time.sleep(0.5)

        except Exception as e:
            print(f"  ❌ Failed to select group: {e}")
            raise

    def select_members_multi_select(self, username: str):
        """
        Add member to 'Choose members' multi-select (GROUP-centric form).
        """
        print(f"  ⏳ Adding member: {username}")

        try:
            # Find the multi-select input (look for select2-container-multi)
            container = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    ".select2-container-multi"))
            )
            input_field = container.find_element(By.CSS_SELECTOR, "input.select2-input")

            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", input_field)
            time.sleep(0.2)
            input_field.click()
            time.sleep(0.3)

            # Type the username
            input_field.clear()
            input_field.send_keys(username)
            time.sleep(1.5)  # Wait for autocomplete

            # Click matching result
            try:
                result_item = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR,
                        ".select2-results li.select2-result-selectable"))
                )
                result_item.click()
                print(f"  ✅ Added member: {username}")
            except:
                input_field.send_keys(Keys.RETURN)
                print(f"  ✅ Added member via Enter: {username}")

            time.sleep(0.5)

        except Exception as e:
            print(f"  ❌ Failed to add member: {e}")
            raise

    def select_user_reference_field(self, username: str):
        """
        Select user in 'User to modify' field using exact element IDs from HTML.
        Container: s2id_sp_formfield_user_reference
        Search input: s2id_autogen191_search (appears after dropdown opens)
        """
        print(f"  ⏳ Selecting user: {username}")

        try:
            # Click the Select2 container to open the dropdown
            # Use the choice link inside the container for more reliable click
            script = """
            (function() {
                var container = document.getElementById('s2id_sp_formfield_user_reference');
                if (!container) return {'success': false, 'error': 'Container not found'};

                var choice = container.querySelector('a.select2-choice');
                if (choice) {
                    choice.scrollIntoView({block: 'center'});
                    choice.click();
                    return {'success': true, 'method': 'choice-click'};
                }

                container.click();
                return {'success': true, 'method': 'container-click'};
            })();
            """
            result = self.driver.execute_script(script)
            if not result or not result.get('success'):
                # Fallback to Selenium click
                container = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "s2id_sp_formfield_user_reference"))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", container)
                container.click()

            time.sleep(0.8)  # Wait for dropdown to fully open

            # Wait for dropdown to be active and search input to be ready
            # The dropdown shows "Searching..." initially - wait for it to be ready
            WebDriverWait(self.driver, 5).until(
                lambda d: d.find_element(By.CSS_SELECTOR, ".select2-drop-active")
            )

            # Find and interact with search input
            search_input = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    ".select2-drop-active input.select2-input"))
            )

            # Use JavaScript to type - more reliable than send_keys
            self.driver.execute_script("""
                var input = arguments[0];
                var value = arguments[1];
                input.focus();
                input.value = value;
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}));
            """, search_input, username)

            time.sleep(1.5)  # Wait for autocomplete results

            # Click matching result
            try:
                result_item = WebDriverWait(self.driver, 8).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR,
                        ".select2-results li.select2-result-selectable"))
                )
                result_item.click()
                print(f"  ✅ Selected user: {username}")
            except:
                # Fallback: press Enter
                search_input.send_keys(Keys.RETURN)
                print(f"  ✅ Selected user via Enter: {username}")

            time.sleep(0.5)

        except Exception as e:
            print(f"  ❌ Failed to select user: {e}")
            raise

    def select_group_list_field(self, group_name: str):
        """
        Add group to 'Choose groups' multi-select field using exact element IDs from HTML.
        Container: s2id_sp_formfield_group_list
        Search input: s2id_autogen192 (inside the multi-select container)
        """
        print(f"  ⏳ Adding group: {group_name}")

        try:
            # Click on the multi-select input field
            input_field = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "s2id_autogen192"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", input_field)
            time.sleep(0.2)
            input_field.click()
            time.sleep(0.3)

            # Type the group name
            input_field.clear()
            input_field.send_keys(group_name)
            time.sleep(1.5)  # Wait for autocomplete

            # Click matching result
            try:
                result_item = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR,
                        ".select2-results li.select2-result-selectable"))
                )
                result_item.click()
                print(f"  ✅ Added group: {group_name}")
            except:
                input_field.send_keys(Keys.RETURN)
                print(f"  ✅ Added group via Enter: {group_name}")

            time.sleep(0.5)

        except Exception as e:
            print(f"  ❌ Failed to add group: {e}")
            raise

    def select_members_field(self, username: str):
        """
        Add member (user) to 'Choose members to add to or remove from the group' field.
        This is a multi-select field for users.
        """
        print(f"  ⏳ Adding member: {username}")

        try:
            # Find the members multi-select field by label
            script = """
            (function() {
                var labels = document.querySelectorAll('label');
                for (var i = 0; i < labels.length; i++) {
                    var text = labels[i].textContent;
                    if (text.includes('Choose members') || text.includes('add to or remove from')) {
                        var formGroup = labels[i].closest('.form-group');
                        if (formGroup) {
                            var input = formGroup.querySelector('input.select2-input');
                            if (input) {
                                input.focus();
                                input.click();
                                return {'success': true, 'method': 'input'};
                            }
                            var container = formGroup.querySelector('.select2-container');
                            if (container) {
                                container.click();
                                return {'success': true, 'method': 'container'};
                            }
                        }
                    }
                }
                return {'success': false};
            })();
            """
            self.driver.execute_script(script)
            time.sleep(0.3)

            # Type in the search input
            search_input = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    ".select2-container-active input.select2-input, .select2-drop-active input.select2-input"))
            )
            search_input.clear()
            search_input.send_keys(username)
            time.sleep(1)  # Wait for autocomplete

            # Click matching result
            try:
                result_item = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR,
                        ".select2-results li.select2-result-selectable"))
                )
                result_item.click()
                print(f"  ✅ Added member: {username}")
            except:
                search_input.send_keys(Keys.RETURN)
                print(f"  ✅ Added member via Enter: {username}")

        except Exception as e:
            print(f"  ❌ Failed to add member: {e}")
            raise

    def submit_ad_group_request(
        self,
        groups: List[str],
        users: List[str],
        justification: str,
        dry_run: bool = False
    ):
        """
        Submit AD group membership request.
        Handles the "Choose Options" page (Page 2) which is USER-centric:
        1. User to modify (s2id_sp_formfield_user_reference)
        2. Choose groups (s2id_sp_formfield_group_list) - multi-select
        3. Add/Remove (sp_formfield_addremove)
        4. Business Justification (sp_formfield_busjust)

        Args:
            groups: List of AD group names to request access to
            users: List of usernames to add to the groups
            justification: Business justification for the request
            dry_run: If True, don't actually submit (stop before final confirmation)
        """
        print(f"\n🚀 Submitting AD Group Request:")
        print(f"   Groups: {', '.join(groups)}")
        print(f"   Users: {', '.join(users)}")
        print(f"   Justification: {justification[:50]}...")

        print("\n📝 Filling out Choose Options form (Page 2)...")

        # Wait for page 2 to fully load
        time.sleep(1)

        # The form is GROUP-centric when selecting "One Group":
        # 1. Group name (first Select2 dropdown)
        # 2. Choose members (multi-select for users)
        # 3. Add/Remove dropdown
        # 4. Business Justification

        # First, we MUST expand the accordion to see the form fields
        # The accordion row contains "Modify Active Directory Group Membership"
        print("  ⏳ Expanding accordion...")

        # Use JavaScript to expand the accordion - more reliable than Selenium click
        expand_script = """
        (function() {
            // Find the accordion item containing "Modify Active Directory"
            var items = document.querySelectorAll('[id^="item_name_"]');
            for (var i = 0; i < items.length; i++) {
                var text = items[i].textContent || '';
                if (text.includes('Modify Active Directory')) {
                    // Find the accordion-toggle parent and click it
                    var toggle = items[i].closest('.accordion-toggle');
                    if (toggle) {
                        toggle.click();
                        return {'success': true, 'method': 'toggle'};
                    }
                    // Try panel-heading
                    var heading = items[i].closest('.panel-heading');
                    if (heading) {
                        heading.click();
                        return {'success': true, 'method': 'heading'};
                    }
                }
            }

            // Alternative: Click on the row with "Options" text
            var rows = document.querySelectorAll('.panel-heading .row[role="button"]');
            for (var i = 0; i < rows.length; i++) {
                var text = rows[i].textContent || '';
                if (text.includes('Modify Active Directory')) {
                    rows[i].click();
                    return {'success': true, 'method': 'row'};
                }
            }

            // Last resort: Click the chevron icon
            var chevrons = document.querySelectorAll('.fa-chevron-down');
            if (chevrons.length > 0) {
                var parent = chevrons[0].closest('[ng-click]') || chevrons[0].closest('.panel-heading');
                if (parent) {
                    parent.click();
                    return {'success': true, 'method': 'chevron'};
                }
            }

            return {'success': false, 'error': 'Could not find accordion'};
        })();
        """
        try:
            result = self.driver.execute_script(expand_script)
            if result and result.get('success'):
                print(f"  ✅ Expanded accordion ({result.get('method')})")
                time.sleep(1.5)  # Wait for accordion animation
            else:
                print(f"  ⚠️ Accordion expansion may have failed: {result}")
        except Exception as e:
            print(f"  ⚠️ Accordion JS failed: {e}")

        # Wait for form fields to be visible inside the expanded accordion
        # Look for "Group name" label to confirm form is visible
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Group name')]"))
            )
            print("  ✅ Form fields are visible")
        except:
            print("  ⚠️ Form fields may not be fully loaded, trying to continue...")

        # Fill the GROUP-centric form with ALL users
        group = groups[0]

        self.fill_page2_group_centric_form(group, users, justification)

        print(f"\n✅ Page 2 form filled successfully with {len(users)} user(s)")

        if dry_run:
            print("\n🔍 DRY RUN MODE - Stopping before final submission")
            print("   Review the form in the browser and submit manually if correct")
            input("   Press Enter to close the browser...")
            return

        # Step 6: Click Next to proceed to Summary (same button ID as page 1)
        print("\n  ⏳ Clicking Next to proceed to Summary...")
        try:
            next_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "submit"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView(true);", next_btn)
            time.sleep(0.3)
            next_btn.click()
            print("  ✅ Clicked Next button")
        except:
            # Fallback
            try:
                self.wait_and_click(By.XPATH, "//button[contains(text(), 'next')]", "Next button (fallback)")
            except:
                self.driver.execute_script("angular.element(document.body).scope().$apply(function() { angular.element(document.body).scope().goNext(); });")
                print("  ✅ Navigated via Angular goNext()")
        time.sleep(2)

        # Step 7: Submit the request from Summary page
        print("\n📤 Submitting request...")
        submit_selectors = [
            "//button[contains(text(), 'Submit')]",
            "//button[contains(text(), 'Confirm')]",
            "//button[contains(text(), 'Order Now')]",
            "//button[contains(@class, 'submit')]",
        ]

        for selector in submit_selectors:
            try:
                self.wait_and_click(By.XPATH, selector, "Submit button")
                break
            except:
                continue

        time.sleep(3)

        # Try to capture the request number
        try:
            success_msg = self.driver.find_element(
                By.XPATH,
                "//*[contains(@class, 'success') or contains(@class, 'confirmation') or contains(text(), 'REQ') or contains(text(), 'submitted')]"
            )
            print(f"\n✅ Request submitted successfully!")
            print(f"   {success_msg.text}")
        except NoSuchElementException:
            print("\n✅ Request appears to have been submitted (check ServiceNow for confirmation)")

    def close(self):
        """Close the browser."""
        if self.driver:
            self.driver.quit()
            print("\n🔒 Browser closed")


def main():
    parser = argparse.ArgumentParser(
        description="Batch AD Group membership requests on ServiceNow (one request per group)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Request multiple groups for multiple users (one request per group)
  python ad_group_batch.py --groups "GROUP1,GROUP2,GROUP3" --users "user1,user2" --justification "Team access"

  # Dry run (navigate to form but don't submit)
  python ad_group_batch.py --groups "GROUP1,GROUP2" --users "user1" --justification "Test" --dry-run
        """
    )

    parser.add_argument(
        "--groups", "-g",
        required=True,
        help="Comma-separated list of AD group names (one request per group)"
    )
    parser.add_argument(
        "--users", "-u",
        required=True,
        help="Comma-separated list of usernames to add to ALL groups"
    )
    parser.add_argument(
        "--justification", "-j",
        required=True,
        help="Business justification for the request"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (not recommended for SSO)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Navigate to form but don't submit (for testing)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout in seconds for element waits (default: 30)"
    )

    args = parser.parse_args()

    # Parse comma-separated lists
    groups = [g.strip() for g in args.groups.split(",")]
    users = [u.strip() for u in args.users.split(",")]

    print("=" * 60)
    print("🤖 ServiceNow AD Group Request Automation - BATCH MODE")
    print("=" * 60)
    print(f"Groups ({len(groups)}): {groups}")
    print(f"Users ({len(users)}): {users}")
    print(f"Justification: {args.justification}")
    print(f"Mode: {'Dry Run' if args.dry_run else 'Live'}")
    print(f"Total requests to create: {len(groups)}")
    print("=" * 60)

    automation = None
    successful_groups = []
    failed_groups = []

    try:
        automation = ServiceNowADAutomation(
            headless=args.headless,
            timeout=args.timeout
        )

        # Authenticate once
        automation.navigate_to_servicenow()

        # Process each group as a separate request
        for i, group in enumerate(groups, 1):
            print("\n" + "=" * 60)
            print(f"📋 Processing Group {i}/{len(groups)}: {group}")
            print("=" * 60)

            try:
                # Navigate to AD request form (starts fresh for each group)
                automation.navigate_to_ad_request(num_groups=1)

                # Submit request for this group with all users
                automation.submit_ad_group_request(
                    groups=[group],
                    users=users,
                    justification=args.justification,
                    dry_run=args.dry_run
                )

                successful_groups.append(group)
                print(f"\n✅ Group {i}/{len(groups)} completed: {group}")

                # If not dry run and more groups to process, go back to main page
                if not args.dry_run and i < len(groups):
                    print("\n🔄 Navigating back for next group...")
                    automation.driver.get(automation.SERVICENOW_URL)
                    time.sleep(3)

            except Exception as e:
                print(f"\n❌ Failed to process group {group}: {e}")
                failed_groups.append((group, str(e)))

                # Try to recover by going back to main page
                if i < len(groups):
                    try:
                        print("🔄 Attempting to recover for next group...")
                        automation.driver.get(automation.SERVICENOW_URL)
                        time.sleep(3)
                    except:
                        pass

        # Summary
        print("\n" + "=" * 60)
        print("📊 BATCH SUMMARY")
        print("=" * 60)
        print(f"✅ Successful: {len(successful_groups)}/{len(groups)}")
        for group in successful_groups:
            print(f"   - {group}")

        if failed_groups:
            print(f"\n❌ Failed: {len(failed_groups)}/{len(groups)}")
            for group, error in failed_groups:
                print(f"   - {group}: {error[:50]}...")

        print("=" * 60)

    except KeyboardInterrupt:
        print("\n\n⚠️ Automation interrupted by user")
    except Exception as e:
        print(f"\n❌ Automation failed: {e}")
        if automation:
            try:
                automation.driver.save_screenshot("/tmp/servicenow_error.png")
                print("📸 Screenshot saved to /tmp/servicenow_error.png")
            except:
                pass
        sys.exit(1)
    finally:
        if automation:
            automation.close()


if __name__ == "__main__":
    main()

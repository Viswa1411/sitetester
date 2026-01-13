
import json

def compare_dom_elements(base_elements, compare_elements):
    """
    Compares two lists of DOM elements to find additions, removals, and style changes.
    
    Args:
        base_elements (list): List of element dicts from the baseline URL.
        compare_elements (list): List of element dicts from the comparison URL.
        
    Returns:
        list: A list of diff objects.
    """
    diffs = []
    
    # Convert lists to dictionaries tracked by a unique index to handle duplicates (multiple elements with same text)
    # We use a simple greedy matching: first come, first served for identical elements.
    unmatched_base = {i: el for i, el in enumerate(base_elements)}
    
    # We also keep track of what we've matched in compare to identify additions
    # Actually, we can just iterate compare_elements and pop from unmatched_base.
    
    for comp_el in compare_elements:
        match_index = -1
        
        # Priority 1: ID Match (if ID exists and is not empty)
        if comp_el.get('id'):
            for i, base_el in unmatched_base.items():
                if base_el.get('id') == comp_el.get('id') and base_el['tag'] == comp_el['tag']:
                    match_index = i
                    break
        
        # Priority 2: Text + Tag Match (if no ID matched or ID missing)
        if match_index == -1:
            for i, base_el in unmatched_base.items():
                if base_el['tag'] == comp_el['tag'] and base_el['text'] == comp_el['text']:
                    match_index = i
                    break
        
        if match_index != -1:
            # We found a match! Check for style differences.
            base_el = unmatched_base.pop(match_index)
            
            style_diffs = {}
            target_styles = ['color', 'background-color', 'font-family', 'font-size', 'font-weight', 'text-align']
            
            base_styles = base_el.get('styles', {})
            comp_styles = comp_el.get('styles', {})
            
            for prop in target_styles:
                val1 = base_styles.get(prop)
                val2 = comp_styles.get(prop)
                
                # Simple string comparison (browser should normalize to rgb/px usually)
                if val1 != val2:
                    # Ignore minor float diffs in pixels if needed, but for now exact match
                    style_diffs[prop] = {
                        'old': val1,
                        'new': val2
                    }
            
            if style_diffs:
                diffs.append({
                    'type': 'style_change',
                    'rect': comp_el['rect'], # Use the new position for highlighting
                    'diffs': style_diffs,
                    'tag': comp_el['tag'],
                    'text': comp_el['text']
                })
        else:
            # No match found in base -> It's ADDED in the new version
            diffs.append({
                'type': 'added',
                'rect': comp_el['rect'],
                'tag': comp_el['tag'],
                'text': comp_el['text']
            })
    
    # Any remaining items in unmatched_base are MISSING in the new version (Removed)
    for base_el in unmatched_base.values():
        diffs.append({
            'type': 'removed',
            'rect': base_el['rect'], # Use the old position to highlight where it WAS
            'tag': base_el['tag'],
            'text': base_el['text']
        })
        
    return diffs
